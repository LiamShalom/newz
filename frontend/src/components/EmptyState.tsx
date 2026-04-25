/**
 * Feed empty state — verbatim UI-SPEC copy. Centered on the dark feed background.
 * UI-SPEC token discipline: every color is from the seven approved tokens.
 */
export function EmptyState() {
  return (
    <div className="min-h-[100dvh] bg-[#0A0A0A] flex flex-col items-center justify-center px-6 text-center">
      <h1 className="text-2xl font-semibold leading-[1.2] text-[#FAFAFA]">
        No clips yet
      </h1>
      <p className="mt-4 text-base leading-[1.5] text-[#A3A3A3]">
        Tap the red button to record one.
      </p>
    </div>
  );
}
