# Alex - the Agentic Learning Equities Test

> # Running Alex locally
>
> This copy of Alex (`fa_alex`) runs only on this PC. All the AWS parts (Terraform, Lambda packaging, deploy scripts, Aurora, SQS, S3 Vectors, SageMaker, Bedrock, App Runner) have been removed.
>
> - **Database:** Postgres with pgvector, running in Docker (container `fa-alex-postgres`). It holds the app data and the knowledge base.
> - **AI models and embeddings:** OpenAI. Each analysis costs a few cents of OpenAI usage.
> - **Agents:** the API starts the planner as a local process, and the planner runs the other agents the same way.
> - **Share prices:** Yahoo Finance through yfinance. No key needed. ASX tickers use the `.AX` suffix (for example `BHP.AX`) and are priced in AUD.
>
> ## What you need (one-time)
>
> - **Docker Desktop**, Node.js, uv and Google Chrome installed.
> - **The root `.env` file** with:
>   - `OPENAI_API_KEY`, which is required.
>   - `CLERK_JWKS_URL` and `CLERK_ISSUER`, which sign-in needs.
>   - The Langfuse keys, which are optional. They turn on tracing.
> - **`frontend/.env.local`** with your Clerk keys.
>
> Any AWS values left in `.env` are ignored. Nothing in this copy reads them.
>
> ## Start Alex
>
> 1. Open Docker Desktop and wait until it says it is running.
> 2. In PowerShell:
>
> ```powershell
> cd C:\Users\harryk\projects\fa_alex\scripts
> ```
>
> ```powershell
> uv run start_local.py
> ```
>
> 3. When you see "Alex is running locally", open http://localhost:3000 and sign in.
> 4. Press **Ctrl+C** in that window to stop Alex.
>
> What the script does:
>
> - It starts the database container (`fa-alex-postgres`).
> - On the first run, it loads the 22 starter ETFs.
> - It starts the API on port 8000 and the website on port 3000.
> - The agents' logs appear in the same window.
>
> The original `alex` folder uses the same ports (3000, 8000, 5432), so run only one of the two at a time. Their databases are separate.
>
> ## Run market research (optional)
>
> The researcher browses the web, writes a short analysis and saves it to the knowledge base. The reporter uses that knowledge base for the "Market Context" part of its reports.
>
> Alex must already be running. Run these in a second PowerShell window:
>
> ```powershell
> cd C:\Users\harryk\projects\fa_alex\backend\researcher
> ```
>
> ```powershell
> uv run research_local.py "Nvidia stock outlook"
> ```
>
> - If you leave out the topic, the agent picks one from today's news.
> - A run takes a minute or two.
>
> ## Stop the database
>
> The database keeps running in Docker after you stop Alex. Your data is kept between runs. To stop the database:
>
> ```powershell
> cd C:\Users\harryk\projects\fa_alex
> ```
>
> ```powershell
> docker compose stop
> ```
>
> ## Optional settings
>
> You can set these in `.env`:
>
> | Setting                  | Default                                      | What it does                                                 |
> | ------------------------ | -------------------------------------------- | ------------------------------------------------------------ |
> | `OPENAI_MODEL`           | `gpt-4.1-mini`                               | The model all the agents use                                 |
> | `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small`                     | The embeddings model for the knowledge base. If you change it, keep a model with 1536 dimensions. |
> | `DATABASE_URL`           | `postgresql://alex:alex@localhost:5432/alex` | The local database connection                                |
>
> ## Troubleshooting
>
> - **"Docker is not running":** start Docker Desktop, wait for it to finish starting, then run the script again.
> - **Port 3000, 8000 or 5432 is already in use:** an earlier run, the original `alex` folder, or another app is still running. Stop it (for the original, `docker compose stop` in `C:\Users\harryk\projects\alex`).
> - **An analysis fails:** read the error in the PowerShell window. The most common cause is a missing or invalid `OPENAI_API_KEY`.
> - **A price is missing:** Yahoo has no price for that ticker. ASX tickers need `.AX`. The stored price is kept.
> - **Log lines mentioning "instrumentor" or "force_flush":** these are harmless tracing warnings. You can ignore them.
> - **Start the database from empty:** run `docker compose down -v` in the `fa_alex` folder. This **deletes all local data** for this copy. The next start reloads the starter ETFs.
