"use client";
import useSWR from "swr";
import { Plus } from "lucide-react";
import { useApp } from "@/components/app-context";
import { WatchCard } from "@/components/watch-card";
import { useWatchDialog } from "@/components/watch-dialog";
import { Button, Empty, PageHeader, Spinner } from "@/components/ui";
import { fetcher } from "@/lib/client";
import { checkNote } from "@/lib/watch-logic";
import type { WatchRow } from "@/lib/watch-types";

export default function WatchesPage() {
  const { data, isLoading } = useSWR<WatchRow[]>("/watches", fetcher);
  const { me } = useApp();
  const watch = useWatchDialog();

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader
        title="Watchlist"
        sub={`Flights you're keeping an eye on. ${checkNote(Boolean(me?.guest))} Set a price alert on any of them to hear when it gets cheaper.`}
        actions={
          <Button variant="primary" onClick={() => watch.edit()}>
            <Plus className="size-4" /> Watch a flight
          </Button>
        }
      />
      {isLoading && <Spinner />}
      {data && !data.length && (
        <Empty
          title="You're not watching any flights yet"
          action={
            <Button variant="primary" onClick={() => watch.edit()}>
              <Plus className="size-4" /> Watch a flight
            </Button>
          }
        >
          Pick a route and the dates you could travel, and FlightScout keeps checking the price for you. You can also tap Watch on
          any search.
        </Empty>
      )}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {data?.map((w) => (
          <WatchCard key={w.id} w={w} all={data} />
        ))}
      </div>
      {watch.element}
    </div>
  );
}
