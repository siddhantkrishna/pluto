import { NextResponse } from "next/server";

// Used only when no API rewrite is configured. Never pretend an account was created.
export const dynamic = "force-dynamic";

function unavailable() {
  return NextResponse.json(
    {
      error: {
        message: "PLUTO's account service is temporarily unavailable. Please contact the administrator.",
      },
    },
    {
      status: 503,
      headers: { "Cache-Control": "no-store" },
    },
  );
}

export const GET = unavailable;
export const POST = unavailable;
export const PUT = unavailable;
export const PATCH = unavailable;
export const DELETE = unavailable;
export const HEAD = unavailable;
export const OPTIONS = unavailable;
