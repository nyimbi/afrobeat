import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { GenerationProgress } from "../generation-progress"
import type { JobStatus } from "@/lib/types"

function renderProgress(overrides: Partial<Parameters<typeof GenerationProgress>[0]> = {}) {
	return render(
		<GenerationProgress
			status="ml_generating"
			progressPercent={42}
			statusMessage="Composing your track..."
			{...overrides}
		/>,
	)
}

describe("GenerationProgress", () => {
	it("renders the status message, percent, and all five steps", () => {
		renderProgress()
		expect(screen.getByText("Composing your track...")).toBeInTheDocument()
		expect(screen.getByText("42%")).toBeInTheDocument()
		for (const label of ["Queue", "Compose", "Master", "Upload", "Done"]) {
			expect(screen.getByText(label)).toBeInTheDocument()
		}
	})

	it("exposes an accessible progressbar with clamped values", () => {
		const { rerender } = renderProgress({ progressPercent: 140 })
		expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100")

		rerender(
			<GenerationProgress status="queued" progressPercent={-5} statusMessage="Queued" />,
		)
		expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0")
	})

	it("shows the ETA hint while active", () => {
		renderProgress({ estimatedSeconds: 95 })
		expect(screen.getByText(/~1m 35s left/)).toBeInTheDocument()
	})

	it("hides the ETA once complete", () => {
		renderProgress({ status: "complete", progressPercent: 100, statusMessage: "Ready!", estimatedSeconds: 95 })
		expect(screen.queryByText(/left/)).not.toBeInTheDocument()
		expect(screen.getByText("Ready!")).toBeInTheDocument()
	})

	it("marks completed steps with checkmarks", () => {
		renderProgress({ status: "uploading", progressPercent: 80, statusMessage: "Uploading..." })
		// queued, ml_generating, audio_processing done → three checkmarks
		expect(screen.getAllByText("✓")).toHaveLength(3)
	})

	it("renders failure state without a percent", () => {
		renderProgress({ status: "failed" as JobStatus, progressPercent: 30, statusMessage: "Generation failed." })
		expect(screen.getByText("Generation failed.")).toBeInTheDocument()
		expect(screen.getByText("—")).toBeInTheDocument()
		expect(screen.queryByText("30%")).not.toBeInTheDocument()
	})

	it("renders cancellation distinctly from failure", () => {
		renderProgress({ status: "cancelled" as JobStatus, progressPercent: 30, statusMessage: "Generation cancelled." })
		expect(screen.getByText("Generation cancelled.")).toBeInTheDocument()
		expect(screen.getByText("—")).toBeInTheDocument()
	})
})
