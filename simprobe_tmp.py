import numpy as np
from backend.retrieval.embedder import embed_texts

Q = ["Which fare zone is Union metro station in?",
     "What are my options to reach Expo City from Al Qusais using public transport?",
     "What is the nearest stop to Dubai Mall?",
     "ما هي خطوط الحافلات التي تخدم محطة مترو الاتحاد؟",
     "كيف أصل من ديرة سيتي سنتر إلى مول الإمارات بالمترو؟"]
QN = ["en_zone","en_frame","en_near","ar_bus","ar_route"]
E = ["Union Metro Station is a Metro station in Dubai on the Red Metro line in fare zone 5.",
     "Route 13 is a Dubai bus route of type Urban running between GSBS9 and QSDH11. It serves 42 stops.",
     "Expo 2020 Metro Station is on the Red Metro line in fare zone 1.",
     "Al Qusais Metro Station is on the Green Metro line in fare zone 6.",
     "Mall of the Emirates Metro Station is a Metro station on the Red Metro line in fare zone 2.",
     "Deira City Centre Metro Station is a Metro station on the Green Metro line in fare zone 5.",
     "The Dubai Mall (Bus) - 0.09 km. Burj Khalifa Lake - 0.14 km.",
     "Dubai Taxi Corporation reported 613 limousine drivers in March 2022."]
EN = ["union","route","expo","qusais","mall","deira","geo","IRREL"]
qv = embed_texts(Q, batch_size=8); ev = embed_texts(E, batch_size=8)
sim = qv @ ev.T
print("         " + "".join(f"{k:>8}" for k in EN))
for i,k in enumerate(QN):
    print(f"{k:<9}" + "".join(f"{sim[i][j]:>8.3f}" for j in range(len(EN))))
pairs = {"en_zone":{"union"}, "en_frame":{"expo","qusais"}, "en_near":{"geo"},
         "ar_bus":{"union","route"}, "ar_route":{"mall","deira"}}
rel=[]; irr=[]
for i,k in enumerate(QN):
    for j,e in enumerate(EN):
        (rel if e in pairs[k] else irr).append(float(sim[i][j]))
print()
print(f"RELEVANT   n={len(rel)} min={min(rel):.3f} mean={np.mean(rel):.3f} max={max(rel):.3f}")
print(f"IRRELEVANT n={len(irr)} min={min(irr):.3f} mean={np.mean(irr):.3f} max={max(irr):.3f}")
print(f"separation (rel_min - irr_max) = {min(rel)-max(irr):+.3f}")
