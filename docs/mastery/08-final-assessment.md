# Mastery 08 — Final Assessment

Answer these by reasoning about the actual code. No lookup should be needed if
you have internalized the architecture; check yourself against the referenced
lessons.

## Section A — Architecture reasoning

1. A new endpoint `POST /organizations/{slug}/reports` should be manager+ only
   and write an audit row. List, in order, every file you touch and the
   responsibility you put in each. Which layer gets the rank check, and why not
   the router?
2. The task list endpoint calls `TaskRepository` directly from the router. A
   reviewer flags it as a layering violation. Defend or reject the flag using
   the criteria in `architecture/02`.
3. `app/services/comments.py` could compute mentions itself. It calls
   `events.notify`. What architectural property does that preserve?
4. Why do repositories only `flush`? Give a concrete multi-write operation in
   TeamFlow that would break if they committed.
5. Where does the `organization_id` used in queries *come from* for
   `GET /tasks/{id}`? Name every hop.

## Section B — Transactions and failure behavior

6. Trace `POST /projects/{id}/tasks` with a valid webhook configured. State the
   commit points, what is durable after each, and what the client sees if the
   broker dies between commit #2 and the enqueue.
7. An `Idempotency-Key` request handler raises a 500 after partially writing
   domain data that then rolls back. What is the idempotency row's state, and
   what happens when the client retries with the same key?
8. Two requests with the same idempotency key arrive simultaneously on
   different workers. Describe both outcomes (which request gets what status)
   and the mechanism that decides.
9. The webhook task is redelivered by Celery after a worker crash mid-POST.
   Explain, step by step, why the receiver does not process the event twice
   (and what the receiver must still do).
10. `cleanup_expired_data` runs twice concurrently (someone ran beat twice).
    Which of its three purges are safe to double-run and why?

## Section C — Auth and tenancy

11. A user with a valid refresh token calls `GET /auth/me` with it as the Bearer
    token. What happens in the current code, what *should* happen, and where is
    the one-line fix?
12. A member of Org A guesses a task ID in Org B. Name every check that runs and
    the exact status code returned at each step.
13. The same member (now in their own org) tries to assign a task to a user who
    is only in Org B. Which function rejects it, and with what error class?
14. An admin demotes a manager. Which rank comparison permits it? Now the admin
    tries to promote a member to admin — why does the *same* code reject it?
15. Why are roles resolved per request rather than embedded in the JWT? Give the
    concrete behavior difference when a role changes mid-session.

## Section D — Async behavior

16. Which single call in the auth endpoints blocks the event loop, for how long,
    and why is that accepted? What is the upgrade path?
17. `presign_put` is called inline in an async handler but `storage.stat` is
    offloaded. Explain the difference precisely.
18. You add an endpoint that calls a partner API with `requests`. Describe the
    production symptom, the immediate fix, and the correct long-term pattern.
19. Why do Celery workers use sync sessions instead of the async engine? What
    constraint does that impose on reusing service code there?
20. What breaks if `expire_on_commit=True` on the async session factory?

## Section E — Realtime and scaling

21. With `--workers 4`, alice (socket on worker 1) must receive bob's
    `task.created` (request handled by worker 3). Trace the full path and name
    the Redis channel.
22. What does the WS listener do when Redis restarts? What do connected clients
    experience, and what is the documented data loss window?
23. Why can't `ConnectionManager.broadcast` be called by the service layer
    directly, and what bug does that produce on one worker vs many?
24. A slow client stalls `send_to_room` for the whole room. Name the design
    limitation and the standard upgrade.

## Section F — Database performance

25. Count the SQL queries for `GET /organizations/{slug}/tasks?limit=20` and
    name each. Where would an N+1 appear if the loader strategies were removed?
26. Which index serves `?overdue=true`? Which serves the dashboard's status
    counts? Why do both lead with `organization_id`?
27. `?search=payment` cannot use an index. Explain why and give the PostgreSQL
    fix at scale.
28. Why does `refetch_task` use `populate_existing=True`? What user-visible bug
    appears without it (which endpoint, which response field)?
29. Offset pagination vs keyset: state the failure at 10k+ rows and the
    migration path that keeps the `Page[T]` response shape.

## Section G — Infrastructure failure modes

30. Redis is flushed. Enumerate what breaks, what degrades, and what keeps
    working (per use: refresh, rate limit, cache, pub/sub).
31. The Celery broker is down for an hour. What is lost, what is delayed, and
    what compensates?
32. MinIO is down. Which endpoints fail, which degrade, and why is it absent
    from `/health/ready`?
33. A webhook receiver returns 500 repeatedly. How many attempts, what backoff,
    what final state, and where does an operator look?
34. The SMTP provider is down during a password reset. What does the user
    experience, and what does the audit trail show?

## Section H — Review and judgment

35. You are reviewing an agent-generated endpoint. It: accepts `organization_id`
    in the body, uses `db.get(Task, id)`, commits in the router, and has no
    `response_model`. List four concrete defects with severity.
36. Same review: the agent added `lazy="joined"` to `Task.labels`. Explain the
    row-multiplication bug and the correct strategy.
37. The agent added a new Redis key with no TTL and no degradation path. Why is
    this a production incident waiting to happen in *this* codebase's design
    philosophy?
38. The agent embedded `role` in the JWT "for performance". Give two concrete
    failures this causes in TeamFlow.
39. The agent's test mocks the SQLAlchemy session. Explain what class of bugs it
    cannot catch, using a concrete TeamFlow example.
40. Pick the S1 finding from `production/07` and write: the fix, the regression
    test, and the review-checklist item that would have caught it.

---

## Scoring

- **36–40 correct:** you can review agent-generated FastAPI code responsibly.
- **28–35:** re-read the sections where you stumbled; the codebase is the
  answer key.
- **<28:** the architecture lessons (`02`, `architecture/*`) and the mastery map
  (`07`) are the highest-value re-reads.

## Suggested written format for each answer

```
Trigger → layer(s) involved → exact check/queries → outcome (status/log) → failure mode if changed
```
