# Alpha

Alpha is a small HTTP API that serves order data.

## Setup

Run `make dev` to start the server on port 8080.

### Linux

Install `libpq-dev` before building.

## Rate limiting

Requests are limited per client with a token bucket from `golang.org/x/time/rate`.
See `internal/ratelimit` for the middleware.
