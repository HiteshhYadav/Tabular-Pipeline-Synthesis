/**
 * Asks for the server's access token. Shown only when /health reports
 * auth_required and the browser holds no accepted token - a local deployment
 * without API_TOKENS never sees it.
 *
 * The input is type=password so the token is not left on screen, and the
 * form never echoes a refused token back: "that token was refused" is enough
 * to act on.
 */

import { useState, type FormEvent } from "react";
import { Button } from "./Button";
import { Card } from "./Card";

export function AccessTokenPanel({
  rejected,
  onSubmit,
}: {
  rejected: boolean;
  onSubmit: (token: string) => void;
}) {
  const [token, setToken] = useState("");

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (token.trim()) onSubmit(token.trim());
  }

  return (
    <Card className="mb-6">
      <form onSubmit={handleSubmit} className="space-y-4" aria-labelledby="access-title">
        <div>
          <p className="label-caps text-text-tertiary">Access required</p>
          <h2 id="access-title" className="mt-1 text-heading font-heading text-text-primary">
            Enter your access token
          </h2>
          <p className="mt-1 text-secondary-size text-text-secondary">
            This server only accepts requests with a token. It is kept in this browser and sent
            only to this server.
          </p>
        </div>
        {rejected ? (
          <p role="alert" className="text-secondary-size text-error">
            That token was refused. Check it and try again.
          </p>
        ) : null}
        <div className="flex flex-wrap items-center gap-3">
          <label className="sr-only" htmlFor="access-token">
            Access token
          </label>
          <input
            id="access-token"
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={token}
            onChange={(event) => setToken(event.target.value)}
            className="min-w-64 flex-1 rounded-sm border border-border bg-surface px-3 py-2 font-mono text-data text-text-primary outline-none focus:border-accent focus:ring-2 focus:ring-focus-ring"
            placeholder="Access token"
          />
          <Button type="submit" disabled={!token.trim()}>
            Continue
          </Button>
        </div>
      </form>
    </Card>
  );
}
