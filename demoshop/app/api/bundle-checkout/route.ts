import { NextResponse } from "next/server";

type BundleCheckoutRequest = {
  laptopId?: string;
  includeSleeve?: boolean;
  studentCode?: string;
  deliveryMethod?: string;
};

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

export async function POST(request: Request): Promise<NextResponse> {
  const bundle = await request.json() as BundleCheckoutRequest;
  await wait(1_200);

  const isValidCampusBundle = bundle.laptopId === "nova-13"
    && bundle.includeSleeve
    && bundle.studentCode?.trim().toUpperCase() === "STUDENT15";

  if (!isValidCampusBundle) {
    return NextResponse.json(
      { error: "The campus bundle configuration is incomplete." },
      { status: 400 },
    );
  }

  if (bundle.deliveryMethod === "Express delivery (next day)") {
    // Intentional functional defect: discounted express orders are valid in the UI
    // but rejected by the order validator. Loop should capture this 409 response.
    return NextResponse.json(
      { error: "Student pricing could not be validated for express delivery." },
      { status: 409 },
    );
  }

  return NextResponse.json({ orderId: "demo-campus-order", status: "confirmed" });
}
