import { redirect } from "next/navigation";

// Explore lives on the main search page now (shown while no destination is set).
export default function ExplorePage() {
  redirect("/");
}
