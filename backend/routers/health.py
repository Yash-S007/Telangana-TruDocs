from fastapi import APIRouter

from backend.core.hierarchy import _adangal, _market_value, _pattadar, _prohibited_lands, _survey_map

router = APIRouter()


@router.get("/api/health")
def health():
    return {
        "status": "ok",
        "hierarchy": {
            "pattadar_villages": len(_pattadar()),
            "adangal_villages": len(_adangal()),
            "survey_map_villages": len(_survey_map()),
            "market_value_villages": len(_market_value()),
            "prohibited_lands_villages": len(_prohibited_lands()),
        },
    }
