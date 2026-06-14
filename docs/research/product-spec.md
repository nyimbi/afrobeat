# Gbẹdu — AI Afrobeats Music Generator: Product Specification

**Version:** 0.1 (Pre-seed)  
**Date:** 2026-06-14  
**Status:** Research-grounded draft — all technical claims sourced from `docs/research/afrobeats-generator-research.md`

---

## 1. Product Vision

**Gbẹdu** (Yoruba/Lagos slang: *the music, the vibe, the party*) is a mobile-first AI platform that lets anyone — from a Surulere teenager to a Lagos producer to a Nigerian-British university student — create, own, and distribute professional-quality Afrobeats music in under two minutes, using only their voice and a text prompt.

**One-sentence positioning:**  
*Suno for Afrobeats, built for Africa.*

**Why this, why now:**
- Afrobeats Spotify streams grew 550% from 2017–2022 and are still accelerating. Audiomack alone has served 58B Afrobeats streams in Nigeria.
- No AI music tool targets Afrobeats or supports Nigerian Pidgin, Yoruba, or Igbo.
- Spotify's September 2025 AI policy established the commercial path: AI music is permitted, with vocal impersonation restricted to artist-authorized use.
- Open-weight models (ACE-Step 1.5, YuE, Stable Audio 3.0 Medium) now make genre-fine-tuned music generation viable without proprietary APIs.

---

## 2. Target Users

Three personas, one platform. Design for the first two; the third arrives via word-of-mouth.

### Persona A — Aisha, 19, Lagos (The Fan/Creator)
Has no music production skills. Loves Tems, Ayra Starr, Rema. Wants to make a song for her birthday, for a TikTok challenge, or just because she heard a beat in her head. Will pay nothing up front but will share everything. **Acquisition vector: TikTok challenges and friend referrals.**

### Persona B — Chukwu, 26, Accra / East London (The Emerging Artist)
Makes music on GarageBand or FL Studio, uploads to Audiomack. Has 3K SoundCloud followers. Can't afford studio time or a professional mixing engineer. Needs quality beats, hooks, and stems he can build on. Will pay for tools that make him sound bigger than his budget. **Acquisition vector: producer Discord servers and Afrobeats Twitter.**

### Persona C — Yemi, 34, Lagos (The Working Producer)
Produces for three mid-tier Afrobeats artists. Needs a beat-generation engine to prototype ideas faster. Will use Gbẹdu as a starting point, not an endpoint. **Acquisition vector: referral from Persona B.**

---

## 3. Core Product — Feature Specification

### 3.1 Track Generation (MVP — Weeks 1–6)

**Input surface:**
```
[Mood/Vibe prompt text field]        e.g. "Late night on Lagos island, romantic, Afropop"
[Sub-genre selector]                 Afropop | Afrofusion | Alte | Amapiano-cross | Afrobeats-UK
[Language selector]                  English | Nigerian Pidgin | Yoruba | Igbo | Mix
[Energy level slider]                Chill 1 ——————●—— Turnt 10
[BPM override] (optional)           Auto-detect from sub-genre | Manual (80–130 BPM)
[Duration]                           30s preview | 1 min | 2 min | Full (3–4 min)
[Generate] button
```

**Output:**
- Streaming audio playback (no download until user saves)
- Waveform visualization
- Auto-generated lyrics shown inline, editable
- "Regenerate lyrics only" / "Regenerate beat only" / "Regenerate both" controls
- Save to Library → triggers full 3-min generation if preview was shorter

**Generation constraints:**
- Free tier: max 3 full generations/day, watermarked audio, non-commercial
- Creator tier: unlimited, no watermark, commercial license
- Generation target latency: <90 seconds wall-clock for a 3-minute track (A10G GPU)

---

### 3.2 Voice & Vocal Layer (MVP Week 3+)

**Vocalist selection:**
- **AI vocalist presets:** 5–8 pre-trained Afrobeats voice archetypes (husky male, melodic female, gritty street, smooth highlife-cross, etc.) — trained via RVC on consented/synthetic voice data
- **Your voice:** User uploads 30 seconds of their own singing or speaking → RVC conversion applied to AI-generated vocal melody

**Lyric generation controls:**
- Auto (AI writes all lyrics based on prompt)
- Co-write (AI generates, user edits line-by-line before vocal rendering)
- Upload (user pastes their own lyrics, AI sets them to melody)

**Language handling:**
- Lyrics engine: fine-tuned Llama-3 8B on a curated corpus of 50K+ Afrobeats songs in English, Pidgin, Yoruba, and Igbo (see §6.2 for fine-tuning plan)
- Romanized Yoruba with tonal markers rendered in UI; audio uses TTS model trained on native speakers
- Pidgin: fine-tune on scraped lyric corpus + community-contributed validation set

---

### 3.3 Studio Mode (Creator & Pro tier — Phase 2, Month 2–3)

**Stem download (demucs-powered):**
- After generation, export individual stems: Drums | Bass | Melody | Vocals
- 24-bit WAV, 44.1kHz
- Each stem usable in any DAW

**Remix mode:**
- Upload an existing beat (MP3/WAV, ≤10MB)
- AI adds: hook, bridge, or full vocal arrangement on top
- Useful for producers with original beats who want AI vocal completion

**Beat browser:**
- Catalogue of 500+ pre-generated Afrobeats instrumentals (regenerated on demand)
- Filter by BPM, key, sub-genre, energy
- Purchase individual beats from other Gbẹdu users (marketplace — Phase 3)

---

### 3.4 Distribution (Pro tier — Phase 3, Month 4–6)

**Built-in distribution to:**
- Audiomack (primary for Africa — 58B stream volume confirms PMF)
- Spotify via DistroKid-compatible distributor integration (subject to Spotify AI disclosure requirements)
- YouTube (with auto-generated lyric video)
- Apple Music
- Boomplay (pan-African)

**Distribution requirements enforced at upload:**
- AI disclosure tag (DDEX standard, per Spotify September 2025 policy)
- Vocal impersonation check: if user selected an artist-named voice preset, block unless artist has opted in
- ISRC auto-assignment and PRO metadata for partial-AI works (ASCAP/BMI/SOCAN accept these)

**Royalty dashboard:**
- Aggregate streaming revenue across platforms
- Monthly payout via mobile money (M-Pesa, Flutterwave, Paystack) or bank transfer

---

### 3.5 Social & Viral Mechanics

**Share card:** Every generated track gets a share card with:
- 15-second auto-clip of the catchiest moment (peak energy detection via librosa)
- Waveform animation
- "Made with Gbẹdu" branding (removable on Pro tier)
- One-tap share to TikTok, Instagram Reels, WhatsApp Status

**Challenges system:**
- Weekly "Gbẹdu Challenge" — themed prompt (e.g., "Detty December vibes"), top submissions voted by community
- Winners get Pro subscription + featured placement
- Drives organic UGC without paid acquisition

**Collab links:**
- Share a project link → collaborator can edit lyrics, swap vocalist, change vibe
- Async collaboration model (not real-time)

---

## 4. Technical Architecture

### 4.1 Generation Pipeline

```
User Input (prompt + controls)
         │
         ▼
┌─────────────────────────────┐
│   Prompt Engineering Layer  │  Translates UI controls into model-ready prompts
│   (FastAPI + Pydantic)      │  + injects Afrobeats genre priors
└────────────┬────────────────┘
             │
     ┌───────┴────────┐
     ▼                ▼
┌─────────┐    ┌───────────────┐
│  Music  │    │    Lyrics     │
│  Engine │    │    Engine     │
│         │    │               │
│ACE-Step │    │ Llama-3 8B   │
│  1.5    │    │ (fine-tuned   │
│(LoRA-   │    │  on Afrobeats │
│fine-    │    │  corpus)      │
│tuned)   │    │               │
└────┬────┘    └──────┬────────┘
     │                │
     ▼                ▼
┌─────────────────────────────┐
│      Vocal Synthesis        │
│   RVC (preset archetypes)   │
│   or User Voice Conversion  │
└────────────┬────────────────┘
             │
             ▼
┌─────────────────────────────┐
│      Post-Processing        │
│  demucs (stem isolation)    │
│  pedalboard (EQ/comp/verb)  │
│  matchering (mastering)     │
└────────────┬────────────────┘
             │
             ▼
        Final Audio (WAV/MP3)
        + Stems + Metadata
```

### 4.2 Model Stack (Open-Weight Only)

| Layer | Model | License | VRAM (inference) |
|---|---|---|---|
| Music generation | ACE-Step 1.5 (LoRA fine-tuned) | Apache 2.0 | ~8GB |
| Music generation (backup) | Stable Audio 3.0 Medium (1.4B) | Stability Community | ~6GB |
| Long-form generation | YuE 7B | Apache 2.0 | ~14GB |
| Lyric generation | Llama-3 8B (fine-tuned) | Meta Llama 3 Community | ~6GB |
| Vocal synthesis | RVC v2 | MIT | ~4GB |
| Stem separation | Demucs htdemucs_6s | MIT | ~3GB |
| Mastering reference | matchering | GPL-3.0 | CPU |
| Effects chain | pedalboard | GPL-3.0 | CPU |
| Feature extraction | librosa + essentia | ISC / AGPLv3 | CPU |
| Pitch transcription | basic-pitch (Spotify) | Apache 2.0 | CPU |

**Note:** Models are run on cloud GPU fleet, not user devices. No on-device inference in MVP.

### 4.3 Afrobeats Genre Priors (injected into prompt layer)

The following genre knowledge is hard-coded into the prompt engineering layer to bias generation toward authentically Afrobeats outputs:

**BPM range by sub-genre:**
- Afropop: 90–110 BPM
- Afrofusion (Burna Boy-style): 95–115 BPM
- Alte (Santi/Odunsi-style): 80–100 BPM
- Amapiano crossover: 108–116 BPM
- UK Afrobeats (Afroswing): 88–105 BPM

**Percussion DNA:**
- Kick pattern: syncopated, often on beats 1 and 2.5 (not straight 4/4)
- Snare/clap: beat 3 emphasis, ghost notes on 2.75 and 3.75
- Hi-hat: 16th-note subdivision with shuffle feel (~33% swing ratio)
- Shekere/maracas: 8th-note ostinato with accent on beat 1 and 3
- Talking drum (dundun): call-response pattern, typically 4-bar phrase

**Harmonic tendencies:**
- Minor pentatonic and Dorian mode preferred over major
- Common progressions: i–VII–VI–VII, i–III–VII–VI
- Bass: syncopated, emphasizes off-beats; lock with kick drum

**Song structure default template:**
```
[Intro: 8 bars] → [Verse 1: 16 bars] → [Pre-hook: 4 bars] → [Hook: 8 bars]
→ [Verse 2: 16 bars] → [Hook: 8 bars] → [Bridge/Spoken: 4 bars]
→ [Hook × 2: 16 bars] → [Outro: 4 bars fade]
```

**Lyric structure norms:**
- Hook: short, phonetically sticky, mix of English and Pidgin/Yoruba
- Verse: storytelling in Pidgin or English, 8-bar rhyme scheme AABB or ABAB
- Call-and-response phrases between lead and backing vocal common

### 4.4 Infrastructure

**Compute:**
- Inference fleet: NVIDIA A10G (24GB) — 1 GPU can serve ~20 concurrent generations at <90s latency
- Training fleet: A100 80GB (LoRA fine-tuning) — 2-4 GPUs for initial training runs
- Managed via Modal or RunPod (cost-efficient spot GPU)
- Scale: autoscale inference workers 0→N based on queue depth (Celery + Redis)

**Backend:**
- API: FastAPI (Python, async throughout)
- Task queue: Celery + Redis
- Audio storage: Cloudflare R2 (S3-compatible, cheaper egress than AWS S3)
- CDN: Cloudflare (stream audio from edge)
- Database: PostgreSQL (users, tracks, metadata, payments)
- Auth: Keycloak (self-hosted, see infra docs) or Clerk

**Frontend:**
- Web: Next.js 14 (App Router), deployed to Vercel
- Mobile: React Native (iOS + Android) — critical for Africa market
- PWA support: offline playback of saved tracks, installable
- UI language: English (with Pidgin microcopy toggle — "Wetin dey?", "E don generate!")

**Payments:**
- Global: Stripe
- Africa: Paystack (Nigeria, Ghana, Kenya) + Flutterwave
- Mobile money: M-Pesa integration via Flutterwave
- Local currency pricing: NGN, GHS, KES — avoid USD-only pricing

---

## 5. Fine-Tuning Plan (The Critical Path)

The language layer is the hardest problem. This plan is the primary technical risk in the project.

### 5.1 Music Generation Fine-Tuning

**Model:** ACE-Step 1.5  
**Method:** LoRA (documented to work from 8–23 songs; production target: 2,000–5,000 tracks)  
**Hardware:** 2× A100 80GB, estimated 48–96 hours for first run  
**Dataset acquisition strategy:**

| Source | Volume | Status |
|---|---|---|
| Creative Commons Afrobeats (ccMixter, Jamendo) | ~500 tracks | Legal, free |
| Original compositions (commission 10 producers) | ~200 tracks | Requires budget |
| Label licensing deals (start with indie labels) | ~1,000 tracks | Negotiate |
| Public domain pre-1970 highlife/afrobeat | ~300 tracks | Legal, free |
| **Total target** | **2,000 tracks** | — |

**Quality criteria for training data:**
- BPM in 88–120 range
- High-pass filtered: only tracks with audible shekere/talking drum or 16th-note hi-hat patterns
- Minimum 30-second usable segment per track
- No heavy compression artifacts (LUFS > -14 minimum)

**Per sub-genre LoRA adapters:** Train separate LoRA adapters for Afropop, Amapiano-cross, Alte, and Afrofusion. Swap adapters at inference time based on sub-genre selector.

### 5.2 Lyrics Model Fine-Tuning

**Base model:** Llama-3 8B (Meta Community License)  
**Method:** Full SFT fine-tune on lyrics corpus, then RLHF via community ratings  
**Hardware:** 2× A100 80GB, estimated 24–48 hours  

**Corpus targets:**

| Language | Target size | Acquisition |
|---|---|---|
| English Afrobeats lyrics | 30,000 songs | Genius API scrape + cleaning |
| Nigerian Pidgin | 10,000 songs | Genius + AZLyrics + manual curation |
| Yoruba | 5,000 songs | Manual curation + partnership with Yoruba music scholars |
| Igbo | 3,000 songs | Manual curation |
| Mixed (code-switching) | 10,000 songs | Dominant format in contemporary Afrobeats |

**Fine-tuning objectives:**
- Generate Afrobeats-structured lyrics (verse/hook/bridge) given a mood prompt
- Code-switching between English and Pidgin naturally within a verse
- Rhyme scheme adherence (AABB and ABAB)
- Cultural reference accuracy (Lagos slang, party culture, relationship dynamics)

**Critical risk:** Yoruba tonal accuracy in text is hard to evaluate automatically. Plan: human rater panel of 5 native Yoruba speakers for evaluation set; monthly quality reviews.

### 5.3 RVC Voice Model Training

**Method:** Retrieval-based Voice Conversion v2 (MIT license)  
**Target:** 8 pre-trained Afrobeats vocal archetypes

| Voice ID | Description | Training data source |
|---|---|---|
| `afro-male-smooth` | Wizkid/Kizz Daniel register | Commission consenting vocalist |
| `afro-male-gritty` | Street/husky, Olamide register | Commission consenting vocalist |
| `afro-female-melodic` | Ayra Starr/Tems register | Commission consenting vocalist |
| `afro-female-highlife` | Classic highlife soprano | Commission consenting vocalist |
| `afro-male-rap` | Midrange rap, Victony register | Commission consenting vocalist |
| `alte-male` | Softer, indie, Odunsi register | Commission consenting vocalist |
| `alte-female` | Airy, Amaarae register | Commission consenting vocalist |
| `afro-uk-male` | Afroswing, Afrowave register | Commission consenting vocalist |

**Legal note:** All RVC training uses consented, commissioned vocal recordings. No voice cloning of specific named artists. Users who upload their own voice for personal use must agree to ToS prohibiting commercial impersonation.

---

## 6. Monetization

### 6.1 Pricing Tiers

| Tier | Price | Limits | Key Features |
|---|---|---|---|
| **Free** | $0 / NGN 0 | 3 full generations/day | Watermarked audio, non-commercial, 2-min max |
| **Creator** | $9.99/mo · NGN 8,500/mo | Unlimited | No watermark, commercial license, stem download, 4-min max |
| **Pro** | $29.99/mo · NGN 25,000/mo | Unlimited | + Voice cloning, distribution, marketplace selling, API access (100 calls/day) |
| **Label / Studio** | $199/mo | Unlimited | White-label output, batch API (unlimited), dedicated GPU queue, SLA |

**Notes on Africa pricing:**
- NGN prices set to approximate PPP parity, not straight FX conversion
- Offer annual plans at 2 months free (reduces churn)
- Student discount: 50% with .edu.ng email verification

### 6.2 Revenue Streams

1. **Subscriptions** — primary recurring revenue; target 100K Creator tier within 18 months
2. **Beat marketplace** — 20% platform commission on peer-to-peer beat sales
3. **Distribution revenue share** — $1–$2 per album distributed (on top of Pro subscription)
4. **Brand campaigns** — custom AI-generated challenge songs; floor $25K per campaign
5. **API licensing** — B2B access for music apps, social platforms, ad agencies

### 6.3 Unit Economics (Year 1 target)

| Metric | Target |
|---|---|
| Free users | 500,000 |
| Creator subscribers | 50,000 |
| Pro subscribers | 5,000 |
| Label accounts | 50 |
| MRR at 12 months | ~$700K |
| ARR at 12 months | ~$8.4M |
| Gross margin | ~65% (cloud GPU costs dominate COGS) |

GPU cost model: A10G at ~$0.75/hr on RunPod spot; one 3-min Afrobeats generation costs ~$0.04 in compute. Free tier: cost of goods ~$0.12/user/day at 3 generations.

---

## 7. Go-To-Market

### 7.1 Launch Sequence

**Pre-launch (Weeks 1–4): Build the waitlist**
- 30-second demo video: "Watch me make an Afrobeats song in 60 seconds" — shot in Lagos, no studio, phone only
- TikTok and Twitter seeding: tag 20 micro-influencers (50K–200K followers) in Nigerian music community
- "Request early access" landing page — collect phone numbers (WhatsApp), not just emails
- Partner with 3 Afrobeats music YouTubers for early-access giveaways

**Beta (Weeks 5–8): Artist seeding**
- Give free Pro accounts to 50 emerging artists on Audiomack with 1K–50K followers
- Require: 1 song created on Gbẹdu posted publicly, "Made with Gbẹdu" in bio for 30 days
- Track: which artists' followers sign up after hearing the song

**Public launch (Week 9):**
- Launch TikTok challenge: #GbẹduChallenge — "Make your own Afrobeats song and post it"
- Prize pool: NGN 5M split across top 10 entries (viewer votes)
- Press pitch: TechCabal, Techpoint Africa, Okay Africa, The Guardian Nigeria

### 7.2 Retention Mechanics

- **Weekly prompt:** Every Monday, push notification with a fresh themed prompt ("Rain season feels", "Owambe vibes")
- **Creation history:** Library of every track ever generated — nostalgia/pride keeps users returning
- **Collab requests:** "Your friend Chidi wants to add a verse to your track" — social re-engagement
- **Stream notifications:** "Your track just hit 1,000 plays on Audiomack" — dopamine loop tied to real outcomes

### 7.3 Competitive Moat

| Dimension | Suno / Udio | Gbẹdu |
|---|---|---|
| Genre focus | Generic, all genres | Afrobeats-specific LoRA |
| Language | English only | Pidgin, Yoruba, Igbo, English |
| Distribution | Export only | Built-in Audiomack/Spotify |
| Payment | USD/card only | Mobile money, local currency |
| Community | Global generic | African creator community |
| Mobile | Web only | Native mobile app |

Suno and Udio have no reason to invest in a 20-language African fine-tuning program for a market they're not focused on. That's the moat.

---

## 8. Risk Register

| Risk | Severity | Mitigation |
|---|---|---|
| Yoruba/Pidgin lyric quality inadequate | High | Human rater panel; launch with English-primary, add African languages progressively |
| ACE-Step 1.5 Afrobeats fine-tune doesn't reach commercial quality | High | Ensemble with YuE and Stable Audio 3.0 Medium; A/B test outputs |
| Spotify/Audiomack block AI music uploads | Medium | DDEX compliance from day 1; don't use named-artist voice impersonation |
| GPU cost overrun on free tier | Medium | Cap free tier hard at 3/day; aggressive queue management |
| Copyright challenge on training data | High | Use only CC, commissioned, and licensed data; do not scrape YouTube |
| User voice data misuse (GDPR/NDPR) | High | Voice data deleted after RVC conversion; no storage without explicit consent |
| RVC producing impersonation of real artists | High | Classifier running at inference to detect named-artist voice similarity; block + flag |
| Nigerian Pidgin model quality plateau | Medium | Partner with linguistics researchers at UI, UNILAG for corpus curation |

---

## 9. MVP Scope Definition

The MVP ships when these and only these capabilities work end-to-end on mobile:

1. User enters a text prompt + selects sub-genre + selects language
2. Platform generates a 60-second Afrobeats preview in <90 seconds
3. User can play, share to TikTok, or generate a 3-min full track
4. Full track can be downloaded (watermarked) or saved to library
5. Upgrade to Creator tier via Paystack or Stripe
6. Creator tier: clean download, no watermark, commercial license granted

**MVP explicitly excludes:** Voice cloning, stem download, distribution, marketplace, remix mode, Yoruba/Pidgin lyrics (English-only at launch).

---

## 10. Open Questions (From Research)

These must be resolved before Phase 2 architecture is finalized:

1. **Afrobeats fine-tuning baseline:** Commission a 2-week LoRA fine-tune of ACE-Step 1.5 on a 500-track test corpus and human-rate the output against Suno/Udio Afrobeats outputs. Determines whether ACE-Step is viable or YuE becomes primary.

2. **Post-June 2025 AfroBench results:** Evaluate Llama 4 Maverick and Qwen 2.5 72B on Yoruba/Pidgin generation to determine if the 12-point open-weight gap has closed before committing to Llama-3 8B fine-tune.

3. **Audiomack distributor API:** Confirm whether Audiomack accepts automated uploads via API, their AI disclosure requirements, and their Content ID equivalent. This determines the Phase 3 distribution architecture.

4. **Pidgin corpus size:** Partner with a linguistics research group to determine minimum viable corpus size for production-quality Pidgin lyric generation. Current best estimate: 10,000 songs, unverified.

---

## 11. Appendices

### A. Key Sources
See `docs/research/afrobeats-generator-research.md` for the full research report with citations, adversarial verification results, and refuted claims.

### B. Model Repositories
- ACE-Step 1.5: `ACE-Step/ACE-Step` on HuggingFace
- YuE: `m-a-p/YuE` on HuggingFace
- Stable Audio 3.0: `stabilityai/stable-audio-3-medium` on HuggingFace
- N-ATLaS: `NCAIR1/N-ATLaS` on HuggingFace
- Demucs: `facebookresearch/demucs` on GitHub
- RVC v2: `RVC-Boss/RVC-WebUI` on GitHub

### C. Regulatory References
- Spotify AI Policy (Sep 2025): https://newsroom.spotify.com/2025-09-25/spotify-strengthens-ai-protections/
- ASCAP/BMI/SOCAN AI registration: https://www.musicbusinessworldwide.com/ascap-bmi-and-socan-will-now-accept-registrations-of-partially-ai-generated-musical-works/
- Nigeria Data Protection Regulation (NDPR): enforces data minimization and consent for biometric data (voice)
