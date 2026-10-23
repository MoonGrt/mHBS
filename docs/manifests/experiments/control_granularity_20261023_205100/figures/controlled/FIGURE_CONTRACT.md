# Controlled software strategy and hardware-granularity comparison

Question: How much of the i-to-c gap changes when only the software chain program is optimized?

The figure keeps both i-generic and i-opt rather than hiding the optimized result. Within each backend it shows SLotH, i-generic, i-opt, c and t. Both i variants use the same current RTL and cryptographic backend; generic is the original single-loop compiler strategy, opt is four-path loop-invariant dispatch. Each point is measured from the same33-byte KAT and checked against complete signatures, cache and Hash work.

The two equal panels show SHAKE and SHA2 with the same zero-based linear scale, component colors and order. All10 observations and all three requested components are represented. Units are millions of clocks; exact integers and sequential percentage denominators remain in JSON/Markdown. No frequency conversion, artificial waiting, sampling or uncertainty estimates are used.

Reuse the prior Python/matplotlib plot structure with explicit label/order mapping. Export editable SVG/PDF and600dpi PNG. Run source, rendered panel alignment, minimum5pt PDF text and collision audits, then visually inspect both panels.

The controlled generic baseline is not presented as the best software implementation. SHA2 generic no longer satisfies the earlier Remaining<SLotH objective; opt still does. Common100MHz evidence is reusable only by identical RTL hashes, and does not include an external-ROM top timing assertion. Production files and historical figures remain intact.
