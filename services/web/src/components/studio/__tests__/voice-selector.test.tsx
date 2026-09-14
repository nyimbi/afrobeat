import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { VoiceSelector } from "../voice-selector"
import { api } from "@/lib/api"
import type { VoiceModel } from "@/lib/types"

vi.mock("@/lib/api", () => ({
	api: {
		voices: {
			getVoiceModels: vi.fn(),
			getVoiceModelStatus: vi.fn(),
			uploadVoiceModel: vi.fn(),
			deleteVoiceModel: vi.fn(),
		},
	},
}))

const voices = vi.mocked(api.voices)

function vm(overrides: Partial<VoiceModel> = {}): VoiceModel {
	return {
		id: "vm-1",
		name: "Lagos Tenor",
		description: null,
		archetype: "custom",
		status: "ready",
		isPreset: false,
		isPublic: false,
		trainingProgressPercent: 100,
		errorMessage: null,
		createdAt: "",
		...overrides,
	}
}

const preset = () =>
	vm({ id: "preset-1", name: "Amara", archetype: "tems_inspired", isPreset: true })

function renderSelector(props: Partial<Parameters<typeof VoiceSelector>[0]> = {}) {
	return render(
		<VoiceSelector
			value={null}
			onChange={() => {}}
			canClone
			onUpgradeRequired={() => {}}
			{...props}
		/>,
	)
}

beforeEach(() => {
	vi.clearAllMocks()
	voices.getVoiceModels.mockResolvedValue([preset()])
})

describe("VoiceSelector", () => {
	it("lists presets with an AI-voice default", async () => {
		renderSelector()
		await screen.findByText("Amara")
		expect(screen.getByRole("button", { name: /AI voice/ })).toBeInTheDocument()
	})

	it("selecting a ready model notifies the parent", async () => {
		const user = userEvent.setup()
		const onChange = vi.fn()
		renderSelector({ onChange })
		await user.click(await screen.findByText("Amara"))
		expect(onChange).toHaveBeenCalledWith("preset-1")
	})

	it("shows training progress and blocks selection", async () => {
		const user = userEvent.setup()
		const onChange = vi.fn()
		voices.getVoiceModels.mockResolvedValue([
			vm({ id: "vm-9", name: "Mine", status: "training", trainingProgressPercent: 42 }),
		])
		renderSelector({ onChange })
		expect(await screen.findByText(/Training 42%/)).toBeInTheDocument()
		await user.click(screen.getByText("Mine"))
		expect(onChange).not.toHaveBeenCalled()
	})

	it("shows load errors", async () => {
		voices.getVoiceModels.mockRejectedValueOnce(new Error("offline"))
		renderSelector()
		await screen.findByText("offline")
	})

	it("gates cloning behind Pro+ with an upgrade callback", async () => {
		const user = userEvent.setup()
		const onUpgradeRequired = vi.fn()
		renderSelector({ canClone: false, onUpgradeRequired })
		await user.click(screen.getByText(/Clone a voice/))
		expect(onUpgradeRequired).toHaveBeenCalled()
		expect(screen.queryByLabelText("Voice name")).not.toBeInTheDocument()
	})

	it("uploads a clone only with name, file, and consent", async () => {
		const user = userEvent.setup()
		voices.getVoiceModels.mockResolvedValue([])
		voices.uploadVoiceModel.mockResolvedValueOnce(vm({ id: "vm-new", name: "Stage Me" }))
		renderSelector()

		await user.click(screen.getByText(/Clone a voice/))
		const submit = screen.getByText("Start training")
		expect(submit).toBeDisabled()

		await user.type(screen.getByLabelText("Voice name"), "Stage Me")
		expect(submit).toBeDisabled()

		const file = new File(["audio-bytes"], "sample.mp3", { type: "audio/mpeg" })
		const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
		await user.upload(fileInput, file)
		expect(submit).toBeDisabled()

		await user.click(screen.getByText(/I confirm this is my own voice/))
		expect(submit).toBeEnabled()

		await user.click(submit)
		await waitFor(() => {
			expect(voices.uploadVoiceModel).toHaveBeenCalledWith(
				expect.objectContaining({ name: "Stage Me", file }),
			)
		})
		await screen.findByText("Stage Me")
	})

	it("surfaces upload failures", async () => {
		const user = userEvent.setup()
		voices.getVoiceModels.mockResolvedValue([])
		voices.uploadVoiceModel.mockRejectedValueOnce(new Error("file too large"))
		renderSelector()

		await user.click(screen.getByText(/Clone a voice/))
		await user.type(screen.getByLabelText("Voice name"), "Stage Me")
		const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
		await user.upload(fileInput, new File(["x"], "s.mp3", { type: "audio/mpeg" }))
		await user.click(screen.getByText(/I confirm this is my own voice/))
		await user.click(screen.getByText("Start training"))

		await screen.findByText("file too large")
	})

	it("deletes custom models and clears a stale selection", async () => {
		const user = userEvent.setup()
		const onChange = vi.fn()
		voices.getVoiceModels.mockResolvedValue([vm({ id: "vm-1", name: "Mine" })])
		voices.deleteVoiceModel.mockResolvedValueOnce(undefined)
		renderSelector({ value: "vm-1", onChange })

		await user.click(await screen.findByLabelText("Delete Mine"))
		expect(voices.deleteVoiceModel).toHaveBeenCalledWith("vm-1")
		expect(onChange).toHaveBeenCalledWith(null)
		await waitFor(() => {
			expect(screen.queryByText("Mine")).not.toBeInTheDocument()
		})
	})
})
