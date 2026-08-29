# Service Level Objectives (SLOs) & Error Budget Policy

Anuvritti measures operational excellence using service promises that a family would directly recognize.

---

## 1. Family Service Level Promises

### 1.1 Capture Accepted (`SLO_CAPTURE_ACCEPTED`)
- **Family Promise**: When a parent notes an intention, takes a photo, or records a voice note, the server receives and acknowledges it immediately.
- **Specification**: HTTP `POST /captures`, `POST /sparks`, `POST /voice` completes with status $2xx$ in $\le 200\text{ms}$.
- **Target SLO**: **99.9%** availability over a 30-day rolling window.
- **Monthly Error Budget**: 0.1% (43.2 minutes of total allowable degradation per month).

### 1.2 Return Delivered (`SLO_RETURN_DELIVERED`)
- **Family Promise**: When a family opens the app or receives a gentle daily notification, the memory or question is ready without waiting.
- **Specification**: HTTP `GET /returns`, `GET /right-now` completes with status $2xx$ in $\le 100\text{ms}$.
- **Target SLO**: **99.5%** availability over a 30-day rolling window.
- **Monthly Error Budget**: 0.5% (3.6 hours of allowable degradation per month).

### 1.3 Film Compiled (`SLO_FILM_COMPILED`)
- **Family Promise**: When an anniversary or annual compilation renders, the video compiler completes the film cleanly without crashing or corrupting frames.
- **Specification**: Memory film rendering job succeeds in $\le 60\text{s}$.
- **Target SLO**: **99.0%** availability over a 30-day rolling window.
- **Monthly Error Budget**: 1.0% (7.2 hours of allowable degradation per month).

---

## 2. Multi-Window Multi-Burn-Rate Alerting

We alert on **Error Budget Consumption Rate**, not on transient spikes or isolated failures.

| Severity | Burn Rate | Budget Consumed | Notification Channel | Window |
|---|---|---|---|---|
| **PAGE (Critical)** | $\ge 14.4\times$ | 2% of budget in 1 hour | PagerDuty / On-Call SRE | 1 Hour |
| **TICKET (High)** | $\ge 6.0\times$ | 5% of budget in 6 hours | Team Issue Queue | 6 Hours |
| **NORMAL** | $< 3.0\times$ | Sustainable consumption | Dashboard Only | 30 Days |

Alerts do not wake engineers for transient network blips that do not threaten our monthly promise to families.
