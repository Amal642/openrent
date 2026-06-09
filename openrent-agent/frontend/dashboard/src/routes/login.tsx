import { useState, type FormEvent } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { KeyRound, LoaderCircle, LockKeyhole, UserRound, Zap } from "lucide-react";
import { z } from "zod";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { login, setAuthToken } from "@/auth";

const loginSearchSchema = z.object({
  next: z.string().optional(),
  reason: z.enum(["expired"]).optional(),
});

export const Route = createFileRoute("/login")({
  validateSearch: loginSearchSchema,
  head: () => ({
    meta: [
      { title: "Sign in - Land Royal" },
      { name: "description", content: "Sign in to the Land Royal Command Center." },
    ],
  }),
  component: LoginPage,
});

function LoginPage() {
  const { next, reason } = Route.useSearch();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const response = await login(username, password);
      setAuthToken(response.token);
      const destination = next?.startsWith("/") && !next.startsWith("//") ? next : "/";
      window.location.replace(destination);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 429) {
        setError("Too many login attempts. Please wait and try again.");
      } else {
        setError("Invalid username or password.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-background px-4 py-10">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,var(--accent),transparent_35%),radial-gradient(circle_at_bottom_right,var(--secondary),transparent_35%)] opacity-60" />
      <section className="relative w-full max-w-md rounded-xl border bg-card p-6 shadow-xl sm:p-8">
        <div className="mb-7 flex items-center gap-3">
          <div className="flex size-11 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
            <Zap className="size-5" />
          </div>
          <div>
            <p className="font-semibold">Land Royal</p>
            <p className="text-xs text-muted-foreground">Operations workspace</p>
          </div>
        </div>

        <div className="mb-6">
          <div className="mb-3 flex size-10 items-center justify-center rounded-md bg-primary/10 text-primary">
            <KeyRound className="size-5" />
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">Sign in to Command Center</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Enter the CRM administrator credentials to continue.
          </p>
        </div>

        {reason === "expired" && !error && (
          <div className="mb-4 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-foreground">
            Your session expired. Sign in again to continue.
          </div>
        )}
        {error && (
          <div className="mb-4 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </div>
        )}

        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <Label htmlFor="username">Username</Label>
            <div className="relative">
              <UserRound className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                id="username"
                autoComplete="username"
                autoFocus
                className="pl-9"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                required
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <div className="relative">
              <LockKeyhole className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                className="pl-9"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </div>
          </div>
          <Button className="w-full" type="submit" disabled={submitting}>
            {submitting ? (
              <LoaderCircle className="size-4 animate-spin" />
            ) : (
              <KeyRound className="size-4" />
            )}
            {submitting ? "Signing in..." : "Sign in"}
          </Button>
        </form>
      </section>
    </main>
  );
}
