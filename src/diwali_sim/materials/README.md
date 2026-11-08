# materials/

Textures are generated (pure Python) into the models that use them:
- `models/rangoli/materials/textures/{rangoli_mandala,kolam_white}.png`
- `models/festival_banner/materials/textures/banner.png`
Other surfaces use PBR parameters (albedo colour, roughness, metalness) defined inline in each
`model.sdf`. Re-generate everything with `python3 scripts/generate_assets.py`.
