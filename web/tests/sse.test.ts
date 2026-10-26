// @vitest-environment node
import { describe, it, expect } from "vitest";
import { readEvents, type StreamEvent } from "@/lib/sse";
function stream(text: string, split = 1) {
  const bytes = new TextEncoder().encode(text);
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (let i = 0; i < bytes.length; i += split)
        controller.enqueue(bytes.slice(i, i + split));
      controller.close();
    },
  });
}
describe("stream reader", () => {
  it("handles fragmented UTF-8 and completion frames", async () => {
    const events: StreamEvent[] = [];
    await readEvents(
      stream('data: {"token":"café"}\n\ndata: {"done":true}\n\n'),
      (event) => events.push(event),
    );
    expect(events[0].token).toBe("café");
    expect(events.at(-1)?.done).toBe(true);
  });
  it("accepts CRLF framing split across chunks", async () => {
    const events: StreamEvent[] = [];
    await readEvents(stream('data: {"done":true}\r\n\r\n'), (event) =>
      events.push(event),
    );
    expect(events[0].done).toBe(true);
  });
  it("does not mistake a truncated response for success", async () => {
    await expect(
      readEvents(stream('data: {"token":"partial"}\n\n'), () => {}),
    ).rejects.toThrow("interrupted");
  });
  it("surfaces an explicit stream error", async () => {
    await expect(
      readEvents(
        stream('data: {"error":"Access revoked","done":true}\n\n'),
        () => {},
      ),
    ).rejects.toThrow("Access revoked");
  });
});
