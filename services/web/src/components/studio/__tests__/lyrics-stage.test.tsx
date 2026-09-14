import { useState } from "react"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { LyricsStage } from "../lyrics-stage"
import { api } from "@/lib/api"
import type { LyricDraft, LyricsMode } from "@/lib/types"

vi.mock("@/lib/api", () => ({
	api: { lyrics: { draftLyrics: vi.fn() } },
}))

const mockedDraft = vi.mocked(api.lyrics.draftLyrics)

function draft(overrides: Partial<LyricDraft> = {}): LyricDraft {
	return {
		verse1: "Mo dupe o",
		prehook: "",
		hook: "Jaiye ori mi",
		verse2: "",
		bridge: "",
		outro: "",
		fullLyrics: "Mo dupe o\nJaiye ori mi",
		languageUsed: "yoruba",
		fellBackToEnglish: false,
		languageDisclosure: null,
		...overrides,
	}
}

function Harness({ initialMode = "ai" as LyricsMode, prompt = "grateful song" }) {
	const [mode, setMode] = useState<LyricsMode>(initialMode)
	const [text, setText] = useState("")
	return (
		<>
			<LyricsStage
				prompt={prompt}
				subGenre="afrobeats"
				language="yoruba"
				mode={mode}
				onModeChange={setMode}
				lyricsText={text}
				onLyricsTextChange={setText}
			/>
			<output data-testid="lyrics-value">{text}</output>
		</>
	)
}

beforeEach(() => {
	vi.clearAllMocks()
})

describe("LyricsStage", () => {
	it("defaults to surprise-me copy with no editor", () => {
		render(<Harness />)
		expect(screen.getByText(/Gbẹdu writes lyrics during generation/)).toBeInTheDocument()
		expect(screen.queryByLabelText(/editor/i)).not.toBeInTheDocument()
	})

	it("switching modes notifies the parent", async () => {
		const user = userEvent.setup()
		const onModeChange = vi.fn()
		render(
			<LyricsStage
				prompt="x"
				subGenre="afropop"
				language="english"
				mode="ai"
				onModeChange={onModeChange}
				lyricsText=""
				onLyricsTextChange={() => {}}
			/>,
		)
		await user.click(screen.getByRole("button", { name: "Write" }))
		expect(onModeChange).toHaveBeenCalledWith("write")
	})

	it("disables drafting with no theme and no prompt", async () => {
		render(<Harness initialMode="describe" prompt="" />)
		expect(screen.getByRole("button", { name: /draft lyrics/i })).toBeDisabled()
		expect(mockedDraft).not.toHaveBeenCalled()
	})

	it("populates the editor on successful draft", async () => {
		const user = userEvent.setup()
		mockedDraft.mockResolvedValueOnce(draft())
		render(<Harness initialMode="describe" />)

		await user.click(screen.getByRole("button", { name: /draft lyrics/i }))

		await waitFor(() => {
			expect(screen.getByLabelText("Lyric draft editor")).toHaveValue("Mo dupe o\nJaiye ori mi")
		})
		expect(mockedDraft).toHaveBeenCalledWith({
			prompt: "grateful song",
			subGenre: "afrobeats",
			language: "yoruba",
		})
		expect(screen.getByTestId("lyrics-value")).toHaveTextContent("Mo dupe o")
	})

	it("prefers an explicit theme over the vibe prompt", async () => {
		const user = userEvent.setup()
		mockedDraft.mockResolvedValueOnce(draft())
		render(<Harness initialMode="describe" />)

		await user.type(screen.getByLabelText("Lyric theme"), "owo ni koko")
		await user.click(screen.getByRole("button", { name: /draft lyrics/i }))

		await waitFor(() => expect(mockedDraft).toHaveBeenCalled())
		expect(mockedDraft).toHaveBeenCalledWith(
			expect.objectContaining({ prompt: "owo ni koko" }),
		)
	})

	it("keeps draft history and restores earlier drafts", async () => {
		const user = userEvent.setup()
		mockedDraft
			.mockResolvedValueOnce(draft({ fullLyrics: "first words", hook: "first words" }))
			.mockResolvedValueOnce(draft({ fullLyrics: "second words", hook: "second words" }))
		render(<Harness initialMode="describe" />)

		await user.click(screen.getByRole("button", { name: /draft lyrics/i }))
		await screen.findByDisplayValue("first words")
		await user.click(screen.getByRole("button", { name: /regenerate draft/i }))
		await screen.findByDisplayValue("second words")

		expect(screen.getByRole("button", { name: "Draft 1" })).toBeInTheDocument()
		expect(screen.getByRole("button", { name: "Draft 2" })).toBeInTheDocument()

		await user.click(screen.getByRole("button", { name: "Draft 1" }))
		expect(screen.getByLabelText("Lyric draft editor")).toHaveValue("first words")
	})

	it("shows an error and no editor when drafting fails", async () => {
		const user = userEvent.setup()
		mockedDraft.mockRejectedValueOnce(new Error("ML service unavailable"))
		render(<Harness initialMode="describe" />)

		await user.click(screen.getByRole("button", { name: /draft lyrics/i }))

		await screen.findByRole("alert")
		expect(screen.getByRole("alert")).toHaveTextContent("ML service unavailable")
		expect(screen.queryByLabelText("Lyric draft editor")).not.toBeInTheDocument()
	})

	it("surfaces the English-fallback disclosure from the draft", async () => {
		const user = userEvent.setup()
		mockedDraft.mockResolvedValueOnce(
			draft({
				fullLyrics: "fallback words",
				fellBackToEnglish: true,
				languageDisclosure: "Generated in English — Yoruba generation is experimental",
			}),
		)
		render(<Harness initialMode="describe" />)

		await user.click(screen.getByRole("button", { name: /draft lyrics/i }))
		await screen.findByDisplayValue("fallback words")
		expect(screen.getByText(/Generated in English/)).toBeInTheDocument()
	})

	it("write mode inserts the section template and edits flow to the parent", async () => {
		const user = userEvent.setup()
		render(<Harness initialMode="write" />)

		await user.click(screen.getByText("Insert section template"))
		const editor = screen.getByLabelText("Lyrics editor") as HTMLTextAreaElement
		expect(editor.value).toContain("[VERSE 1]")
		expect(editor.value).toContain("[OUTRO]")

		await user.clear(editor)
		await user.type(editor, "my line")
		expect(screen.getByTestId("lyrics-value")).toHaveTextContent("my line")
	})
})
