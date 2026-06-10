import { useState, type FormEvent } from "react";
import { createFileRoute } from "@tanstack/react-router";
import {
  ArrowRight,
  Check,
  Eye,
  EyeOff,
  LoaderCircle,
  LockKeyhole,
  ShieldCheck,
  UserRound,
} from "lucide-react";
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
      { title: "Sign in - Command Center" },
      { name: "description", content: "Sign in to the Command Center." },
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
  const [showPassword, setShowPassword] = useState(false);

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
    <main className="relative min-h-screen overflow-hidden bg-background">
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(to_right,var(--border)_1px,transparent_1px),linear-gradient(to_bottom,var(--border)_1px,transparent_1px)] bg-[size:64px_64px] opacity-20" />
      <div className="pointer-events-none absolute -left-40 -top-40 size-[32rem] rounded-full bg-primary/10 blur-3xl" />
      <div className="pointer-events-none absolute -bottom-56 -right-40 size-[38rem] rounded-full bg-accent/50 blur-3xl dark:bg-primary/5" />

      <div className="relative mx-auto grid min-h-screen w-full max-w-7xl lg:grid-cols-[1.08fr_0.92fr]">
        <section className="hidden flex-col justify-between px-12 py-10 lg:flex xl:px-20 xl:py-14">
          <Brand />

          <div className="max-w-xl pb-10">
            <h1 className="text-5xl font-semibold leading-[1.08] tracking-[-0.045em] xl:text-6xl">
              Everything your team needs to keep outreach moving.
            </h1>
            <p className="mt-6 max-w-lg text-base leading-7 text-muted-foreground">
              Monitor live conversations, manage accounts, and keep every opportunity visible
              from one secure command center.
            </p>

            <div className="mt-10 grid max-w-lg grid-cols-2 gap-x-8 gap-y-4 text-sm">
              <Feature>Live operational overview</Feature>
              <Feature>Account and worker controls</Feature>
              <Feature>Lead activity in one place</Feature>
              <Feature>Secure seven-day sessions</Feature>
            </div>
          </div>

        </section>

        <section className="flex min-h-screen items-center justify-center px-4 py-8 sm:px-8 lg:border-l lg:bg-card/35 lg:px-12">
          <div className="w-full max-w-md">
            <div className="mb-10 lg:hidden">
              <Brand />
            </div>

            <div className="rounded-2xl border bg-card/95 p-6 shadow-[0_24px_80px_-36px_rgb(15_23_42_/_0.35)] backdrop-blur sm:p-8">
              <div className="mb-8">
                <div className="mb-5 flex items-center gap-2 text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">
                  <ShieldCheck className="size-4 text-success" />
                  Secure access
                </div>
                <h2 className="text-3xl font-semibold tracking-[-0.035em]">Welcome back</h2>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  Sign in with your administrator credentials to continue.
                </p>
              </div>

              {reason === "expired" && !error && (
                <div
                  className="mb-5 rounded-lg border border-warning/40 bg-warning/10 px-3.5 py-3 text-sm text-foreground"
                  role="status"
                >
                  Your session expired. Sign in again to continue.
                </div>
              )}
              {error && (
                <div
                  className="mb-5 rounded-lg border border-destructive/40 bg-destructive/10 px-3.5 py-3 text-sm text-destructive"
                  role="alert"
                >
                  {error}
                </div>
              )}

              <form className="space-y-5" onSubmit={handleSubmit}>
                <div className="space-y-2">
                  <Label htmlFor="username">Username</Label>
                  <div className="relative">
                    <UserRound className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      id="username"
                      autoComplete="username"
                      autoFocus
                      className="h-11 bg-background/70 pl-10 shadow-none"
                      placeholder="Enter your username"
                      value={username}
                      onChange={(event) => setUsername(event.target.value)}
                      required
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="password">Password</Label>
                  <div className="relative">
                    <LockKeyhole className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      id="password"
                      type={showPassword ? "text" : "password"}
                      autoComplete="current-password"
                      className="h-11 bg-background/70 pl-10 pr-11 shadow-none"
                      placeholder="Enter your password"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      required
                    />
                    <button
                      type="button"
                      className="absolute right-1.5 top-1/2 flex size-8 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                      onClick={() => setShowPassword((visible) => !visible)}
                      aria-label={showPassword ? "Hide password" : "Show password"}
                    >
                      {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                    </button>
                  </div>
                </div>

                <Button className="h-11 w-full shadow-sm" type="submit" disabled={submitting}>
                  {submitting ? (
                    <LoaderCircle className="size-4 animate-spin" />
                  ) : (
                    <ArrowRight className="size-4" />
                  )}
                  {submitting ? "Signing in..." : "Sign in"}
                </Button>
              </form>

              <div className="mt-6 flex items-center justify-center gap-2 border-t pt-5 text-xs text-muted-foreground">
                <LockKeyhole className="size-3.5" />
                Protected access for authorised users only
              </div>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}

function Brand() {
  return (
    <div className="flex items-center gap-3">
      <div className="flex size-10 items-center justify-center rounded-xl bg-foreground text-sm font-semibold tracking-[-0.04em] text-background shadow-sm">
        CC
      </div>
      <div className="leading-tight">
        <p className="text-sm font-semibold tracking-tight">Command Center</p>
        <p className="mt-0.5 text-xs text-muted-foreground">Operations</p>
      </div>
    </div>
  );
}

function Feature({ children }: { children: string }) {
  return (
    <div className="flex items-center gap-2.5 text-muted-foreground">
      <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-success/10 text-success">
        <Check className="size-3" strokeWidth={2.5} />
      </span>
      <span>{children}</span>
    </div>
  );
}
