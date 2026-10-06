import React from 'react';

/* The Floor Pov FP mark (sidebar and header brand). A 32px slot with a copy
   for each common screen scaling (125% and 150% are usual on Windows), so the
   browser never stretches a smaller one and blurs it; the small copies have
   their letter cuts widened so F and P stay apart. Decorative: the FLOOR POV
   wordmark beside it carries the name. */
const FP_MARK_SCALES = [[40, '1.25x'], [48, '1.5x'], [64, '2x'], [96, '3x']];

export default function FpMark() {
  const base = process.env.PUBLIC_URL;
  return (
    <img
      className="mk"
      src={`${base}/fp-mark-32.png`}
      srcSet={FP_MARK_SCALES.map(([px, x]) => `${base}/fp-mark-${px}.png ${x}`).join(', ')}
      width="32"
      height="32"
      alt=""
    />
  );
}
