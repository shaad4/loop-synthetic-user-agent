import { NextResponse } from "next/server";

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

export async function POST(): Promise<NextResponse> {
  // Intentional functional defect for the Loop demonstration.
  // Codex will later replace this failure with a successful checkout response.
  await wait(3_000);

  return NextResponse.json(
    { error: "Checkout service is temporarily unavailable." },
    { status: 500 },
  );
}
