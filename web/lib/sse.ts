export type StreamEvent = {
  token?: string;
  done?: boolean;
  error?: string;
  session_id?: string;
  sources?: Source[];
};
export type Source = {
  source_path: string;
  section_path?: string[];
  content?: string;
  score?: number;
};
export async function readEvents(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: StreamEvent) => void,
) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completed = false;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      buffer = buffer.replace(/\r\n/g, "\n");
      if (buffer.length > 1_000_000)
        throw new Error("Response exceeded its limit");
      let position;
      while ((position = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, position);
        buffer = buffer.slice(position + 2);
        for (const line of frame.split("\n"))
          if (line.startsWith("data: ")) {
            const event = JSON.parse(line.slice(6)) as StreamEvent;
            if (event.error) throw new Error(event.error);
            onEvent(event);
            if (event.done) {
              completed = true;
              await reader.cancel();
              return;
            }
          }
      }
    }
    if (!completed)
      throw new Error("The response was interrupted. Please try again.");
  } finally {
    reader.releaseLock();
  }
}
