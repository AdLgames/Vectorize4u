/**
 * Warning codes, in the words a customer should read.
 *
 * §3.2: "Being honest here prevents refund requests." The copy says what the
 * result will actually look like, before they pay, not after.
 */

export const WARNING_COPY: Record<string, { title: string; detail: string; tone: "warn" | "info" }> = {
  photo_input: {
    title: "Photographs don't vectorize cleanly",
    detail:
      "Here's the best we can do. Photos trace into thousands of colour patches — that's the nature of the format, not a setting you can fix.",
    tone: "warn",
  },
  gradients_banded: {
    title: "Gradients are converted to colour steps",
    detail:
      "SVG tracing turns a smooth gradient into bands. We use the finest steps the tracer supports, but it will not be a true gradient.",
    tone: "warn",
  },
  source_resolution_low: {
    title: "Your image is small",
    detail:
      "We upscaled it before tracing, which helps, but detail that isn't in the original can't be recovered.",
    tone: "info",
  },
  physical_size_assumed: {
    title: "Set the output size before cutting",
    detail:
      "This file has no reliable physical size, so we assumed one. Tell us how wide it should be and the SVG and DXF will open at the right scale.",
    tone: "warn",
  },
  preprocess_backed_off: {
    title: "Cleaning was dialled back",
    detail: "Our filters were changing the artwork too much, so we used a lighter touch.",
    tone: "info",
  },
  alpha_premultiplied_fixed: {
    title: "Fixed premultiplied transparency",
    detail: "Your PNG had premultiplied alpha, which causes dark halos. We corrected it.",
    tone: "info",
  },
  cmyk_converted: {
    title: "Converted from CMYK",
    detail: "Colours were converted to sRGB. Check brand colours before printing.",
    tone: "info",
  },
  exif_rotated: {
    title: "Rotated to match the original orientation",
    detail: "Your photo carried a rotation flag; we applied it.",
    tone: "info",
  },
  low_confidence_classification: {
    title: "We weren't sure what kind of image this is",
    detail:
      "We tried settings from the two most likely types. If the result looks wrong, pick the type by hand in Advanced.",
    tone: "info",
  },
  simplify_stopped_early: {
    title: "Kept the extra detail",
    detail: "Simplifying further would have visibly changed the shapes, so we stopped.",
    tone: "info",
  },
  simplify_skipped_large: {
    title: "Too complex to simplify",
    detail:
      "This traced to a very large number of points. It will open, but it is not suited to a cutting machine.",
    tone: "warn",
  },
  node_spacing_enforced: {
    title: "Adjusted for cutting",
    detail:
      "Points closer than the minimum spacing were merged — dense clusters make vinyl blades tear material.",
    tone: "info",
  },
};

export function describeWarning(code: string) {
  return (
    WARNING_COPY[code] ?? {
      title: code.replace(/_/g, " "),
      detail: "",
      tone: "info" as const,
    }
  );
}
