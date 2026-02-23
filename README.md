# blackroad-digital-identity

Digital identity verification and KYC system for BlackRoad Gov.

## Features
- Create and manage digital identities
- Multi-document submission (passport, license, national ID, utility bill)
- KYC request processing with configurable verification levels
- Audit trail for all identity actions
- Suspend, revoke, and reactivate identities

## Verification Levels
| Level | Requirements |
|-------|-------------|
| unverified | Default state |
| basic | 1 verified document |
| standard | 2 verified documents |
| enhanced | 3+ verified documents including primary ID |

## Usage
```bash
python digital_identity.py create "Alice Smith" "alice@example.com"
python digital_identity.py stats
python digital_identity.py list
python digital_identity.py check <identity_id>
python digital_identity.py report <identity_id>
```

## Run Tests
```bash
pip install pytest
pytest tests/ -v
```
