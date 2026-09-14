"use client"

import { GenerationProgress } from "./generation-progress"
import type { JobStatus } from "@/lib/types"

/** @deprecated Use `GenerationProgress` from `./generation-progress` instead. */
export interface GenerationStepProps {
	status: JobStatus | null
	progressPercent: number
	statusMessage: string
	estimatedSeconds?: number | null
	className?: string
}

/** @deprecated Backwards-compatible alias for `GenerationProgress`. */
export function GenerationStep(props: GenerationStepProps) {
	return <GenerationProgress {...props} />
}
