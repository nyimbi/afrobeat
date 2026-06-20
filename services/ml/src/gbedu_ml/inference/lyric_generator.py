from __future__ import annotations

import asyncio
import re
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from gbedu_core.models.track import Language
from gbedu_core.schemas import GenerationRequest
from gbedu_ml.config import settings
from gbedu_ml.language.quality_gate import PidginYorubaQualityGate
from gbedu_ml.prompts.afrobeats import AfrobeatsPromptEngine, CorpusTarget, get_target

log = structlog.get_logger(__name__)

_SECTION_PATTERN = re.compile(
	r"\[(VERSE\s*1|PRE[- ]?HOOK|HOOK|VERSE\s*2|BRIDGE|OUTRO)\]",
	re.IGNORECASE,
)

_LOAD_RETRY_KWARGS = dict(
	stop=stop_after_attempt(3),
	wait=wait_exponential(multiplier=1, min=2, max=10),
	retry=retry_if_exception_type((OSError, RuntimeError)),
	reraise=True,
)


class LyricResult(BaseModel):
	model_config = ConfigDict(extra="forbid")

	verse1: str = Field(default="")
	prehook: str = Field(default="")
	hook: str = Field(default="")
	verse2: str = Field(default="")
	bridge: str = Field(default="")
	outro: str = Field(default="")
	full_lyrics: str = Field(default="")
	language_used: Language
	fell_back_to_english: bool = Field(default=False)
	structure_retries: int = Field(default=0)
	# User-visible disclosure shown in the UI when generation fell back to English
	language_disclosure: str | None = Field(default=None)


class LyricGenerator:
	"""Llama-3 8B Instruct lyric generator with Afrobeats structural constraints.

	Loaded with 4-bit quantization (bitsandbytes) to fit on a single A100/H100 80 GB
	alongside the audio model. Falls back to English if Yoruba quality gate fails.
	"""

	def __init__(self) -> None:
		self._model: Any = None
		self._tokenizer: Any = None
		self._is_loaded: bool = False
		self._prompt_engine = AfrobeatsPromptEngine()
		self._quality_gate = PidginYorubaQualityGate()

	@property
	def is_loaded(self) -> bool:
		return self._is_loaded

	@retry(**_LOAD_RETRY_KWARGS)
	async def load(self) -> None:
		loop = asyncio.get_event_loop()
		await loop.run_in_executor(None, self._load_sync)

	def _load_sync(self) -> None:
		import torch  # type: ignore[import]
		from transformers import (  # type: ignore[import]
			AutoModelForCausalLM,
			AutoTokenizer,
			BitsAndBytesConfig,
		)

		log.info("lyric_gen.load.start", model=settings.LLAMA_MODEL_ID)

		self._tokenizer = AutoTokenizer.from_pretrained(
			settings.LLAMA_MODEL_ID,
			cache_dir=str(settings.MODEL_CACHE_DIR),
			token=settings.HF_TOKEN,
		)
		self._tokenizer.pad_token = self._tokenizer.eos_token

		bnb_config = BitsAndBytesConfig(
			load_in_4bit=True,
			bnb_4bit_quant_type="nf4",
			bnb_4bit_compute_dtype=torch.float16,
			bnb_4bit_use_double_quant=True,
		)

		self._model = AutoModelForCausalLM.from_pretrained(
			settings.LLAMA_MODEL_ID,
			cache_dir=str(settings.MODEL_CACHE_DIR),
			quantization_config=bnb_config,
			device_map="auto",
			token=settings.HF_TOKEN,
		)
		self._model.eval()

		self._is_loaded = True
		log.info("lyric_gen.load.done", model=settings.LLAMA_MODEL_ID)

	def _validate_structure(self, raw: str, target: CorpusTarget) -> tuple[bool, str]:
		"""Check generated lyrics meet corpus structural targets for line count and density."""
		lines = [
			l for l in raw.splitlines()
			if l.strip() and not _SECTION_PATTERN.match(l.strip())
		]
		line_count = len(lines)
		if not (target.min_lines <= line_count <= target.max_lines):
			return False, f"line_count={line_count} not in [{target.min_lines},{target.max_lines}]"
		if lines:
			avg_wpl = sum(len(l.split()) for l in lines) / len(lines)
			wpl_min, wpl_max = target.words_per_line
			if not (wpl_min - 1 <= avg_wpl <= wpl_max + 1):
				return False, f"avg_wpl={avg_wpl:.1f} not in [{wpl_min - 1},{wpl_max + 1}]"
		return True, "ok"

	async def generate(
		self,
		request: GenerationRequest,
		song_structure: dict[str, Any] | None = None,
	) -> LyricResult:
		assert self._model is not None and self._tokenizer is not None, (
			"LyricGenerator not loaded — call load() first"
		)

		structure = song_structure or {
			"sections": ["verse1", "prehook", "hook", "verse2", "bridge", "outro"]
		}
		target = get_target(request.sub_genre)

		loop = asyncio.get_event_loop()

		# Generate with structural validation — retry up to 2 times on failure.
		# Temperature > 0 means each call produces different output.
		struct_retries = 0
		raw_lyrics = await loop.run_in_executor(None, self._generate_sync, request, structure)
		struct_ok, struct_reason = self._validate_structure(raw_lyrics, target)
		while not struct_ok and struct_retries < 2:
			log.warning(
				"lyric.structure_retry",
				attempt=struct_retries + 1,
				reason=struct_reason,
				sub_genre=request.sub_genre.value,
			)
			struct_retries += 1
			raw_lyrics = await loop.run_in_executor(None, self._generate_sync, request, structure)
			struct_ok, struct_reason = self._validate_structure(raw_lyrics, target)
		if not struct_ok:
			log.warning(
				"lyric.structure_constraint_unmet",
				retries=struct_retries,
				reason=struct_reason,
				sub_genre=request.sub_genre.value,
			)

		# Language quality gates — fall back to English if gate fails.
		fell_back = False
		disclosure: str | None = None

		_gate_checks: dict[Language, tuple] = {
			Language.pidgin: (
				self._quality_gate.check_pidgin,
				{"marker_rate": None},
				"marker_rate",
			),
			Language.yoruba: (
				self._quality_gate.check_yoruba,
				{"char_density": None},
				"char_density",
			),
			Language.swahili: (
				self._quality_gate.check_swahili,
				{"marker_rate": None},
				"marker_rate",
			),
			Language.lingala: (
				self._quality_gate.check_lingala,
				{"marker_rate": None},
				"marker_rate",
			),
			Language.zulu: (
				self._quality_gate.check_zulu,
				{"marker_rate": None},
				"marker_rate",
			),
			Language.twi: (
				self._quality_gate.check_twi,
				{"char_density": None},
				"char_density",
			),
		}

		if request.language in _gate_checks:
			check_fn, extra_log_keys, metric_key = _gate_checks[request.language]
			gate_result = check_fn(raw_lyrics)
			if not gate_result.passed:
				metric_val = getattr(gate_result, metric_key)
				log.warning(
					"lyric.language_fallback",
					requested=request.language.value,
					reason=gate_result.reason,
					confidence=gate_result.confidence,
					**{metric_key: metric_val},
				)
				fallback_request = request.model_copy(update={"language": Language.english})
				raw_lyrics = await loop.run_in_executor(
					None, self._generate_sync, fallback_request, structure
				)
				fell_back = True
				disclosure = (
					f"Generated in English — {request.language.value.title()} "
					f"generation is experimental and quality gate failed"
				)

		sections = self._parse_sections(raw_lyrics)
		return LyricResult(
			verse1=sections.get("verse1", ""),
			prehook=sections.get("prehook", ""),
			hook=sections.get("hook", ""),
			verse2=sections.get("verse2", ""),
			bridge=sections.get("bridge", ""),
			outro=sections.get("outro", ""),
			full_lyrics=raw_lyrics.strip(),
			language_used=Language.english if fell_back else request.language,
			fell_back_to_english=fell_back,
			structure_retries=struct_retries,
			language_disclosure=disclosure,
		)

	def _generate_sync(
		self,
		request: GenerationRequest,
		song_structure: dict[str, Any],
	) -> str:
		import torch  # type: ignore[import]

		lyric_prompt = self._prompt_engine.build_lyric_prompt(request, song_structure)

		messages = [
			{
				"role": "system",
				"content": (
					"You are an expert Afrobeats songwriter and lyricist. "
					"You write authentic, culturally rich lyrics with rhythmic sophistication. "
					"Always output the exact section headers requested and nothing else."
				),
			},
			{"role": "user", "content": lyric_prompt},
		]

		# Llama-3 chat template
		input_ids = self._tokenizer.apply_chat_template(
			messages,
			add_generation_prompt=True,
			return_tensors="pt",
		).to(self._model.device)

		with torch.no_grad():
			output_ids = self._model.generate(
				input_ids,
				max_new_tokens=1024,
				do_sample=True,
				temperature=0.8,
				top_p=0.92,
				repetition_penalty=1.15,
				pad_token_id=self._tokenizer.eos_token_id,
			)

		# Strip the prompt tokens — only decode newly generated tokens
		new_tokens = output_ids[0, input_ids.shape[1]:]
		return self._tokenizer.decode(new_tokens, skip_special_tokens=True)

	def _parse_sections(self, raw: str) -> dict[str, str]:
		"""Split raw model output into named sections via regex on section headers."""
		normalise = {
			"verse 1": "verse1",
			"verse1": "verse1",
			"pre-hook": "prehook",
			"prehook": "prehook",
			"pre hook": "prehook",
			"hook": "hook",
			"verse 2": "verse2",
			"verse2": "verse2",
			"bridge": "bridge",
			"outro": "outro",
		}

		sections: dict[str, str] = {}
		parts = _SECTION_PATTERN.split(raw)

		# parts alternates: [pre-content, header, body, header, body, ...]
		i = 1
		while i < len(parts) - 1:
			header = parts[i].strip().lower()
			body = parts[i + 1].strip()
			key = normalise.get(header)
			if key:
				sections[key] = body
			i += 2

		return sections

	async def unload(self) -> None:
		import torch  # type: ignore[import]

		if self._model is not None:
			del self._model
			self._model = None
		if self._tokenizer is not None:
			del self._tokenizer
			self._tokenizer = None
		if torch.cuda.is_available():
			torch.cuda.empty_cache()
		self._is_loaded = False
		log.info("lyric_gen.unloaded")
