# CfP E2E Tests

End-to-end tests for the Call for Proposals (CfP) process, covering the complete lifecycle from proposal submission through scheduling and public display.

## Quick Start

```bash
# Run E2E tests and browse results at http://localhost:2343
./run_tests_with_app

# Run tests only (normal behavior, DB cleaned up after)
./run_tests tests/test_cfp_e2e.py -v
```

## Test Coverage

The E2E tests cover the following areas:

### 1. Proposal Submission (8 tests)
- Submit all 6 proposal types via web forms:
  - Talk
  - Workshop
  - Youth Workshop
  - Performance
  - Installation
  - Lightning Talk
- Edit proposals in "new" state
- Withdraw proposals

### 2. State Transitions (5 tests)
- Valid state transitions through the CfP state machine
- Invalid transition error handling
- Admin accept/reject workflows
- Full review workflow: `new` → `checked` → `anonymised` → `reviewed` → `accepted` → `finalised`

### 3. Scheduling (7 tests)
- `flask cfp create_venues` command
- `flask cfp set_rough_durations` command
- `flask cfp schedule` dry run and persist modes
- `flask cfp apply_potential_schedule` command
- Schedule validity (no venue overlaps)
- Speaker availability constraints

### 4. Favouriting (7 tests)
- Add/remove favourites via web routes
- Favourites page displays correctly
- Favourite count updates
- Authentication required for favouriting
- **Scheduled proposals appear in public schedule JSON**
- **Schedule page loads correctly**

### 5. Clash Detection (5 tests)
- Overlapping proposals detection
- Adjacent proposals (no overlap)
- Different venues (no conflict)
- `get_conflicting_content()` method
- Clash correction by rescheduling

### 6. ClashFinder Tool (3 tests)
- Finds proposals favourited by same users that overlap
- Empty results when no overlapping favourites
- Prioritizes by favourite overlap count

## Running Tests

### Standard Test Run

```bash
# Run all E2E tests
./run_tests tests/test_cfp_e2e.py -v

# Run specific test class
./run_tests tests/test_cfp_e2e.py::TestCfPScheduling -v

# Run single test
./run_tests tests/test_cfp_e2e.py::TestCfPFavouriting::test_add_favourite -v
```

### Browse Test Results

The `run_tests_with_app` script runs tests and launches a test app so you can browse the resulting data:

```bash
# Run tests, then browse at http://localhost:2343
./run_tests_with_app

# Run specific tests, then browse
./run_tests_with_app tests/test_cfp_e2e.py::TestCfPScheduling -v

# Browse existing test data (without running tests)
./run_tests_with_app --app-only

# Stop the test app
./run_tests_with_app --stop

# Clean up test database when done
./run_tests_with_app --cleanup
```

**Options:**

| Option | Description |
|--------|-------------|
| `--no-app` | Run tests only, don't start the test app |
| `--app-only` | Start test app without running tests |
| `--stop` | Stop the test app |
| `--cleanup` | Clean up test database (drop all tables) |
| `-h, --help` | Show help message |

## Architecture

### Test Database

Tests use a separate database (`emf_site_test`) configured in `config/test.cfg`:

```
SQLALCHEMY_DATABASE_URI = "postgresql://postgres:postgres@postgres/emf_site_test"
```

This database is:
- Created fresh at the start of each test module
- Populated with test data by fixtures
- Torn down at the end (unless `KEEP_TEST_DB=1` is set)

### Test App

The test app (`docker-compose.test.yml`) runs on port 2343 and points to the test database:

```yaml
services:
  test-app:
    ports:
      - "2343:2342"
    environment:
      SETTINGS_FILE: ./config/test.cfg
```

This allows you to:
- Browse the schedule at http://localhost:2343/schedule/{year}
- View proposals and favourites
- Debug test data visually

### Key Fixtures

| Fixture | Scope | Description |
|---------|-------|-------------|
| `app` | module | Flask app instance with test config |
| `db` | module | Database session |
| `client` | function | HTTP test client |
| `cli_runner` | function | Flask CLI test runner |
| `venues` | module | EMF venues created via CLI |
| `proposal_factory` | function | Factory to create proposals |
| `cfp_admin_user` | module | User with `cfp_admin` permission |
| `cfp_reviewers` | module | 10 users with `cfp_reviewer` permission |
| `e2e_speakers` | module | 60 unique speaker users |

### Dynamic Dates

Tests use dynamic dates relative to `event_start()` rather than hardcoded dates:

```python
from models import event_start

def get_event_day(day_offset=0, hour=10, minute=0):
    """Get a datetime during the event."""
    start = event_start()
    return datetime(
        year=start.year,
        month=start.month,
        day=start.day + day_offset,
        hour=hour,
        minute=minute,
    )
```

This ensures tests work regardless of the configured event year.

## Test Data Strategy

### Fresh Data Per Module

- Tests create their own data using `proposal_factory`
- Don't rely on dev fake data
- Module-scoped fixtures for venues, admin users
- Unique speakers per proposal to avoid double-booking

### Proposal Quantities

The scheduling tests create enough proposals to exercise the scheduler:

| Type | Count | Purpose |
|------|-------|---------|
| talk | 15 | Fill slots across 3 stages |
| workshop | 20 | Multiple per venue per day |
| youthworkshop | 10 | One venue, multiple days |
| performance | 8 | Evening slots |
| installation | 5 | Not scheduled by algorithm |
| lightning | 10 | Limited slots per day |

### Validation-Based Testing

Since the scheduler is non-deterministic, tests validate properties rather than exact outputs:

```python
def test_schedule_validity(self, app, db, scheduling_proposals, venues):
    """Test scheduled proposals don't have venue overlaps."""
    scheduled = [p for p in all_proposals if p.scheduled_time]

    # Validate no overlaps (don't check exact times)
    overlaps = verify_no_venue_overlaps(scheduled)
    assert not overlaps
```

## Feature Flags

The test config (`config/test.cfg`) enables required feature flags:

```
CFP = True
CFP_FINALISE = True
LIGHTNING_TALKS = True
LINE_UP = True
SCHEDULE = True
BYPASS_LOGIN = True
```

When using `run_tests_with_app`, the script also enables these flags in the test database so the schedule is visible in the browser.

## Troubleshooting

### Tests pass but schedule is empty

1. Check feature flags are enabled:
   ```bash
   ./run_tests_with_app --app-only
   ```
   The script enables `SCHEDULE`, `LINE_UP`, `CFP` flags automatically.

2. Verify proposals are scheduled:
   ```bash
   docker compose exec app uv run python -c "
   from main import create_app
   app = create_app()
   with app.app_context():
       from models.cfp import Proposal
       scheduled = Proposal.query.filter(
           Proposal.scheduled_time.isnot(None)
       ).count()
       print(f'Scheduled proposals: {scheduled}')
   "
   ```

### Test app won't start

Check if port 2343 is already in use:
```bash
lsof -i :2343
```

Stop any existing test app:
```bash
./run_tests_with_app --stop
```

### Database not cleaned up

Run cleanup manually:
```bash
./run_tests_with_app --cleanup
```

Or drop the test database directly:
```bash
docker compose exec postgres psql -U postgres -c "DROP DATABASE IF EXISTS emf_site_test"
```

## Files

| File | Description |
|------|-------------|
| `tests/test_cfp_e2e.py` | Main E2E test file (35 tests) |
| `tests/conftest.py` | Pytest fixtures including CfP-specific ones |
| `config/test.cfg` | Test configuration |
| `docker-compose.test.yml` | Docker Compose override for test app |
| `run_tests_with_app` | Script to run tests and browse results |
