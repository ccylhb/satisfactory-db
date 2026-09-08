import items from "../data/satisfactory_items.json";
import buildings from "../data/satisfactory_buildings.json";

export function GET() {
  const entries = [
    ...items.map((x: any) => ({
      title: x.title,
      href: `/items/${x.slug}/`,
      sub: `Item · ${x.recipes?.length || 0} recipes`,
      icon: x.icon_file || "",
    })),
    ...buildings.map((x: any) => ({
      title: x.title,
      href: `/buildings/${x.slug}/`,
      sub: `Building · ${x.fields?.powerusage || "?"} MW`,
      icon: x.icon_file || "",
    })),
  ].sort((a, b) => a.title.localeCompare(b.title));
  return new Response(JSON.stringify(entries), {
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}
