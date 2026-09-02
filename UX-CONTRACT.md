# ForgeRouter UX Contract

## Product context

- Audience: technical operators supervising agents, providers and model routing.
- Primary jobs: register agent identities, control eligible LLMs and diagnose routing health.
- Active locale: English UI copy; technical identifiers are preserved verbatim.
- Accessibility target: WCAG 2.2 AA.

## Business-context sources

| Domain / scope | Authoritative source | Source type | Reviewed date |
|---|---|---|---|
| Agent identity, authentication and model opt-outs | `docs/REGRAS_DA_APLICACAO.md` §§2–3 | Domain rules | 2026-09-01 |
| Admin API and persistence | `docs/SPEC.md` §§4–5 | API/data spec | 2026-09-01 |
| Database migrations | `README.md` “Banco de Dados” | Operations contract | 2026-09-01 |

## Visual contract

- Project design context: `DESIGN.md`.
- Existing runtime tokens in `frontend/src/style.css` are canonical; `DESIGN.md` mirrors them.
- Supported themes: dark and light, with shared semantic accents.

## Canonical UI Map

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Select/Listbox | Native select by default; Radix-backed `AgentSelect` for visual agent identity | `frontend/src/main.tsx` + `DESIGN.md` | native / authored agent identity | keyboard + popup + build |
| Form | Existing controlled React form state and shared field styling | `frontend/src/main.tsx` + `frontend/src/style.css` | create / edit | API tests + browser flow |
| Scrollbar | Global application stylesheet | `frontend/src/style.css` | stable-gutter geometry exceptions | static audit + browser |
| CRUD | FastAPI admin routes and dedicated Agents create/edit screens | `app/main.py` + `app/storage.py` | return-to-list / stay-on-edit | API tests + full flow |

## Component behavior

| Component | Default | Hover | Focus | Active | Disabled | Busy | Error |
|---|---|---|---|---|---|---|---|
| Button | semantic label | tonal/border feedback | visible violet ring/border | scale/tone | muted, inert | stable label region | persistent page/form alert |
| Agent identity | image + name | unchanged | inherited from owning control | unchanged | inherited | stable square image | initial fallback |
| Agent selector | selected image + name | raised surface | visible ring | selected check | n/a | n/a | preserve selection |
| Group toggle | cost/capability label + count | brighter border/tone | visible ring | normal vs struck/muted | inert when unavailable | pulse | page alert and reload recovery |

## Flow ledger

| Operation | Trigger | Pending | Success destination | Success feedback | Failure recovery | Focus outcome | Source ref |
|---|---|---|---|---|---|---|---|
| Create agent | Create agent | stable disabled button | Agents list | shared status line | form data preserved + page alert | list context | `docs/REGRAS_DA_APLICACAO.md` §2.3 |
| Edit agent image | Add/change/remove photo | current image remains | Edit agent | shared status line | current server image restored on reload | picker control | `app/main.py` admin routes |
| Toggle model group | Group chip | pulsing chip | same Agents list | shared status line | page alert + refreshed server state | activating chip | `docs/REGRAS_DA_APLICACAO.md` §3 |
| Cancel/back | Cancel / Back to Agents | none | Agents list | none | n/a | list context | established sibling flow |

## Validation and resilience

- Agent image inputs accept image files, crop/downscale to 256px client-side and validate the resulting data URI server-side.
- Agent mutations are pessimistic, block duplicate activation where applicable and reload server state after completion.
- API keys remain masked and are never placed in image, status or error content.
- Native selects remain the canonical platform-owned variant for text-only fields. Agent identity requires the authored Radix-backed variant so every option can render image + name.

## Verification

- Static: premium audit, DESIGN lint and anti-pattern search.
- Runtime: frontend unit tests/build, backend agent API tests and browser checks in dark/light plus narrow viewport.
- Canonical sibling: existing user avatar picker and user identity rows.
