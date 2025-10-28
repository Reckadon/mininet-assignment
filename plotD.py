import pandas as pd
import matplotlib.pyplot as plt

# Load CSVs
steps = pd.read_csv("results_custom/H1_steps.csv")
summary = pd.read_csv("results_custom/H1_summary.csv")

# Normalize domain names
steps['domain'] = steps['domain'].str.strip().str.lower()
summary['domain'] = summary['domain'].str.strip().str.lower()
#drop rows containing ubuntu (leaky queries)
steps = steps[~steps['domain'].str.contains('ubuntu')]
summary = summary[~summary['domain'].str.contains('ubuntu')]
# Count number of DNS servers contacted per domain
servers_visited = steps.groupby('domain')['dns_server_ip'].nunique().reset_index()
servers_visited.columns = ['domain', 'servers_visited']

# Merge with total latency
summary = summary.rename(columns={'total_time_ms': 'latency_ms'})
merged = pd.merge(summary[['domain', 'latency_ms']], servers_visited, on='domain', how='inner')

# Take first 10 domains
top10 = merged.head(10)

# --- Plot 1: Latency per query ---
plt.figure(figsize=(9, 4))
plt.bar(top10['domain'], top10['latency_ms'], color='skyblue', edgecolor='black')
plt.xticks(rotation=45, ha='right')
plt.ylabel("Latency (ms)")
plt.title("Total DNS Resolution Latency (First 10 Domains)")
plt.tight_layout()
plt.savefig("H1_latency.png", dpi=300)
plt.show()

# --- Plot 2: Servers visited per query ---
plt.figure(figsize=(9, 4))
plt.bar(top10['domain'], top10['servers_visited'], color='lightgreen', edgecolor='black')
plt.xticks(rotation=45, ha='right')
plt.ylabel("Servers Visited")
plt.title("Number of DNS Servers Visited (First 10 Domains)")
plt.tight_layout()
plt.savefig("H1_servers.png", dpi=300)
plt.show()

print("✅ Saved plots: H1_latency.png and H1_servers.png")
