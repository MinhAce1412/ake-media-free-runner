import sys
D=max(float(sys.argv[1]),0.1)
# 12 evenly spaced points, avoiding exact first/last frame.
pts=[D*(i+0.5)/12 for i in range(12)]
for x in pts:
    print(f"{x:.3f}")
