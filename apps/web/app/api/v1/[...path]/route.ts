import type { NextRequest } from "next/server";
import { handleApi } from "@/lib/server/api";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
type Context = { params: Promise<{ path: string[] }> };
async function dispatch(req: NextRequest, context: Context) {
  const { path } = await context.params;
  return handleApi(req, path || []);
}
export const GET = dispatch;
export const POST = dispatch;
export const PUT = dispatch;
export const PATCH = dispatch;
export const DELETE = dispatch;
