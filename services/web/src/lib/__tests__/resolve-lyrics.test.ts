import { describe, expect, it } from "vitest"
import { LYRICS_MAX_LENGTH, SECTION_TEMPLATE, resolveApprovedLyrics } from "../lyrics"

describe("resolveApprovedLyrics", () => {
	it("returns null in ai mode even when the editor has text", () => {
		expect(resolveApprovedLyrics("ai", "[HOOK]\nJaiye")).toBeNull()
	})

	it("returns trimmed text in describe mode", () => {
		expect(resolveApprovedLyrics("describe", "  [HOOK]\nJaiye  \n")).toBe("[HOOK]\nJaiye")
	})

	it("returns trimmed text in write mode", () => {
		expect(resolveApprovedLyrics("write", "Mo dupe o")).toBe("Mo dupe o")
	})

	it("returns null for blank editor text so the backend uses AI lyrics", () => {
		expect(resolveApprovedLyrics("describe", "")).toBeNull()
		expect(resolveApprovedLyrics("write", "   \n  ")).toBeNull()
	})
})

describe("lyrics constants", () => {
	it("caps input at 5000 chars", () => {
		expect(LYRICS_MAX_LENGTH).toBe(5000)
	})

	it("template covers all pipeline sections", () => {
		for (const header of ["[VERSE 1]", "[PRE-HOOK]", "[HOOK]", "[VERSE 2]", "[BRIDGE]", "[OUTRO]"]) {
			expect(SECTION_TEMPLATE).toContain(header)
		}
	})
})
