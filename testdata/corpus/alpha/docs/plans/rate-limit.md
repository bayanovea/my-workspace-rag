# Plan: per-client rate limiting

## Why

One client flooded the orders endpoint and starved everyone else.

## Approach

Wrap the router in a middleware that keeps one token bucket per API key.
Buckets refill at 10 requests per second with a burst of 20.

```go
# this is a comment inside a code block, not a heading
limiter := rate.NewLimiter(10, 20)
```
