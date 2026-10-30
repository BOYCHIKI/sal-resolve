import { api } from "@/lib/api";

// The label PDF comes through this server, like everything else: the browser never sees the API or its token.
export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const res = await api.packingLabel(id);
  if (!res.ok) return new Response("Label not found", { status: res.status === 404 || res.status === 422 ? 404 : 502 });
  return new Response(res.body, {
    headers: {
      "content-type": "application/pdf",
      "content-disposition": 'attachment; filename="sal-packing-label.pdf"',
      "cache-control": "no-store",
    },
  });
}
