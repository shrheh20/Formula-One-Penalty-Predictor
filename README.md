# F1 Intelligence System

**AI-powered F1 race analysis and prediction platform for enthusiasts and betting markets (Kalshi, Polymarket)**

## 🎯 What This Does

Combines FIA regulations, broadcast intelligence, social media sentiment, and historical data to predict:
- **Grid penalties** (Component 1 - LIVE NOW)
- Mechanical DNF risks
- Safety car probabilities  
- Qualifying results
- Race strategies
- Team/driver sentiment

## 🚀 Quick Start (Component 1: Grid Penalty Predictor)

### Install
```bash
git clone <your-repo>
cd F1-PenaltyPredictor
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

### Test
```bash
./.venv/bin/python test_component1.py
```

### Run
```bash
# Start API
./.venv/bin/python api.py

# Serve the dashboard
python3 -m http.server 8000
```
Then visit `http://localhost:8000/dashboard.html` while the API is running on `http://localhost:5001`.

## 📊 Component 1: Grid Penalty Predictor

**Status:** ✅ READY TO SHIP

Predicts which drivers will take grid penalties based on:
- FIA 2026 power unit component usage (ICE, TC, EXH, MGU-K, ES, PU-CE, PU-ANC)
- Strategic timing analysis (best/worst circuits for penalties)
- Compounded driver-level risk when multiple components are near or at their allocation limit

### API Endpoints

```bash
GET /api/predictions?race=4           # Penalty predictions
GET /api/drivers                      # All driver component status
GET /api/driver/HAM                   # Specific driver details
GET /api/circuits                     # Strategic circuit analysis
GET /api/betting-insights?race=4      # Betting market insights
GET /api/report/4?name=Bahrain%20GP   # Full race report
GET /api/health                       # Health and loaded data status
GET /api/sources                      # FIA source manifest
```

### Example Output

**High-Risk Driver Alert:**
```json
{
  "driver": "NOR",
  "penalty_probability": 99.8,
  "reasons": [
    "ES limit reached (3/3)",
    "PU-CE limit reached (3/3)"
  ],
  "recommendation": "IMMINENT - Penalty expected this race or next"
}
```

**Strategic Circuit Advice:**
```json
{
  "circuit": "Monza",
  "penalty_impact": "LOW",
  "reason": "Long straights, 3 DRS zones, easy overtaking",
  "expected_positions_lost": 3
}
```

## 📁 Project Structure

```
F1-PenaltyPredictor/
├── component_tracker.py          # Core penalty prediction logic
├── api.py                         # Flask REST API
├── dashboard.html                 # Web dashboard
├── fia_2026_component_snapshot.csv # FIA-backed 2026 component snapshot
├── fia_2026_document_sources.json # Official FIA source manifest
├── test_component1.py             # Test suite
├── DEPLOYMENT.md                  # Deployment guide
└── ROADMAP.md                     # Future components roadmap
```


## 📊 Data Sources

### Current (Component 1)
- FIA official 2026 race document pages
- FIA Technical Delegate reports for PU usage and new PU elements
- Circuit characteristics database
- 2026 power unit sporting regulations

### Planned
- Live timing APIs
- Team radio transcripts
- Social media sentiment
- Weather data
- Press conference transcripts
- Multi-language media sources

## 🔧 Development

### Refresh FIA Data
Update `fia_2026_component_snapshot.csv` and `fia_2026_document_sources.json` when new FIA race documents are published:

```csv
Driver,Car_Number,Team,Component_Type,Count,Limit,As_Of_Race,As_Of_Date,Source_Set
NOR,1,McLaren Mercedes,ES,3,3,Japanese Grand Prix,2026-03-28,australia-china-japan
```

### Contribute
1. Fork the repo
2. Build a new component (see ROADMAP.md)
3. Submit PR with tests

## 📝 Disclaimer

**Not financial advice.** This tool provides analysis based on publicly available data. 
Always do your own research before betting. Past prediction accuracy does not guarantee future results.

## 📄 License

MIT License - See LICENSE file

## 🤝 Connect

- Feedback: [Your Contact]
- Issues: GitHub Issues
- Twitter: [Your Handle]

---

**Built by F1 fans, for F1 fans.** 🏎️💨

Ship fast. Validate predictions. Iterate based on accuracy.
