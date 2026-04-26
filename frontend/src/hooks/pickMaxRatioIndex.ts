/**
 * Returns the index of the largest value in `ratios`.
 * Returns -1 if the array is empty or every value is <= 0
 * (i.e. nothing is visible at all).
 * Ties resolve to the lowest index.
 */
export function pickMaxRatioIndex(ratios: number[]): number {
  let maxIdx = -1;
  let maxVal = 0;
  for (let i = 0; i < ratios.length; i++) {
    if (ratios[i] > maxVal) {
      maxVal = ratios[i];
      maxIdx = i;
    }
  }
  return maxIdx;
}
