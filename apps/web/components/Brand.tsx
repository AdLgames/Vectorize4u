/** The mark: a square outline with a cyan node in the corner. */
export default function Brand({ size = 18 }: { size?: number }) {
  return (
    <span
      aria-hidden
      style={{
        width: size,
        height: size,
        border: "2px solid var(--ink-900)",
        borderRadius: 2,
        position: "relative",
        display: "inline-block",
        flexShrink: 0,
      }}
    >
      <span
        style={{
          position: "absolute",
          inset: "3px 3px auto auto",
          width: size / 3,
          height: size / 3,
          background: "var(--cyan)",
        }}
      />
    </span>
  );
}
