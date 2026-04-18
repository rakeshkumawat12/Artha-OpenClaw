# Artha FinOps — Setup Guide

## 1. Clone the repo
```bash
git clone <repo-url>
cd openclaw
```

## 2. Install dependencies
```bash
pip3 install -r requirements.txt
```

## 3. Set up the database
```bash
python3 skills/artha-finops/db.py
```

## 4. Create your .env file
```bash
cp .env.example .env
```
Or create it manually:
```
TELEGRAM_BOT_TOKEN=your_token_here
ARTHA_ALLOWED_USERS=your_telegram_user_id
```

To get your Telegram token → message `@BotFather` → `/newbot`
To get your Telegram user ID → message `@userinfobot`

## 5. Lock down the DB
```bash
chmod 600 data/artha.db
echo ".env" >> .gitignore
```

## 6. Run the bot
```bash
python3 skills/artha-finops/telegram_bot.py
```

Open your bot on Telegram → send `/start`

---

## Test it works (CLI, no Telegram needed)
```bash
python3 skills/artha-finops/artha.py --input "Received ₹25,000 from ABC Corp for website design"
```
