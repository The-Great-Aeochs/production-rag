import { ImageResponse } from "next/og";
export const alt = "Production RAG — Document search";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export default function Image() {
  return new ImageResponse(
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        width: "100%",
        height: "100%",
        background: "#faf9f6",
        padding: "70px 85px",
        color: "#202b27",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          fontSize: 26,
          letterSpacing: -1,
        }}
      >
        production<span style={{ color: "#d75c35" }}>.</span>rag
      </div>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          marginTop: 75,
          fontSize: 68,
          letterSpacing: -2,
          lineHeight: 1.08,
        }}
      >
        <span>Document search</span>
        <span style={{ color: "#d75c35" }}>with cited answers.</span>
      </div>
      <div
        style={{
          display: "flex",
          marginTop: 40,
          fontSize: 21,
          color: "#69736c",
        }}
      >
        Hybrid retrieval. Cited answers. Workspace access control.
      </div>
    </div>,
    size,
  );
}
