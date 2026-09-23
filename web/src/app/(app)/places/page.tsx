import { redirect } from "next/navigation";

// Favorite airports and cities are managed in Settings.
export default function PlacesPage() {
  redirect("/settings#places");
}
