# GeoFA-plugin til QGIS

> Et plugin til QGIS 3.34+ og QGIS 4, der gør det let at tilføje lag fra GeoFA.

Med pluginet kan du hente GeoFA's temaer direkte ind i QGIS uden selv at skulle opsætte forbindelser til tjenesterne. Det er til kommunale GIS-medarbejdere, konsulenter og alle andre, der arbejder med GeoFA-data i QGIS.

Pluginet er baseret på [Dataforsyningens plugin](https://github.com/SDFIdk/Qgis-dataforsyningen), udviklet af [Dataforsyningen, Klimadatastyrelsen](https://dataforsyningen.dk/) og [Septima](https://septima.dk/).

## Indhold

| Fil / mappe | Hvad er det |
|---|---|
| [`geofa_plugin/`](geofa_plugin) | Selve pluginet (kildekode og `metadata.txt`) |
| [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE) | Skabeloner til fejlmeldinger og forslag |

## Sådan bruger du det

1. Åbn QGIS og gå til **Plugins → Administrer og installer plugins**.
2. Søg efter **GeoFA** og klik **Installer**.
3. Vejledning til opsætning og brug: [geodanmark.dk – GeoFA-vejledninger](https://www.geodanmark.dk/home/vejledninger/geofa/).

## Udvikling

Testene kører uden netværk i en midlertidig QGIS-profil. Kør dem fra repoets rod med OSGeo4W:

```
python-qgis.bat -m unittest geofa_plugin.test.test_qgis_compatibility
```

Brug `python-qgis-ltr.bat` for at teste i QGIS LTR.

**Ny version:** opdatér `version` og `changelog` i `metadata.txt`. ZIP-filen til plugins.qgis.org skal indeholde mappen `geofa/` med indholdet af `geofa_plugin/`, men uden `test/`, `Vejledning/` og `.env`.

## Fejl og forslag

Finder du en fejl, eller har du forslag til forbedringer, så opret et [issue](https://github.com/GeoDanmarkGeoFA/QGIS_Plugin_GeoFA/issues). Du kan også skrive til [geofa@geodanmark.dk](mailto:geofa@geodanmark.dk).

## Licens

GPL-2.0 – se [`LICENSE`](LICENSE).

---

<sub>Del af [GeoDanmarkGeoFA](https://github.com/GeoDanmarkGeoFA) · [Om GeoFA](https://confluence.kds.dk/pages/viewpage.action?pageId=191398876)</sub>
