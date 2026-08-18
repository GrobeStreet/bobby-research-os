"""NON-PRODUCTION sketch for discussion with ANTARES/TROVE maintainers."""

# from antares_devkit.models import BaseFilter
#
# class TroveRubinGWFilter(BaseFilter):
#     REQUIRED_GRAV_WAVE_PROB_REGION = 95.0
#
#     def _run(self, locus):
#         if not locus.grav_wave_events_metadata:
#             return
#         locus.set_tag("trove_rubin_gw_candidate")
