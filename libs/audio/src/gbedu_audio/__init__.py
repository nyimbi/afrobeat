"""
gbedu_audio — DSP, stem separation, mastering, and ML audio toolchain for Gbẹdu.
"""

from gbedu_audio._base import AudioFile, AudioProcessingError, ProcessingResult
from gbedu_audio.analysis import AudioAnalyzer
from gbedu_audio.conversion import AudioConverter
from gbedu_audio.effects import AudioEffectsChain
from gbedu_audio.mastering import AudioMastering
from gbedu_audio.pipeline import AudioPipeline, AudioPipelineResult
from gbedu_audio.separation import StemSeparator

__all__ = [
	# base types
	"AudioFile",
	"AudioProcessingError",
	"ProcessingResult",
	# components
	"AudioAnalyzer",
	"AudioConverter",
	"AudioEffectsChain",
	"AudioMastering",
	"AudioPipeline",
	"AudioPipelineResult",
	"StemSeparator",
]
