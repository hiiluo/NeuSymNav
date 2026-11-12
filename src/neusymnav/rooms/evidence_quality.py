"""Observation-link quality, separate from inferred room semantics and geometry."""
from collections import Counter

EVIDENCE_POLICY_VERSION='room-debug-evidence-v1'
GENERIC_OBJECTS=frozenset({'mirror','door','window','painting','pillow','carpet','rug','curtain','blinds','lamp','floor lamp','ceiling fan','fan','clock','vase'})


def assess_evidence_quality(context):
    rows=context.objects;counts=Counter(r.association_status for r in rows)
    linked=sum(r.evidence_count for r in rows)
    verified=bool(rows) and all(r.association_status=='native_confirmed' and r.evidence_count>0 for r in rows)
    flags=['room_geometry_accuracy_unmeasured','predicted_categories_unverified']
    if not linked:flags.append('object_image_links_missing')
    if any(r.association_status=='ambiguous' or r.membership_status!='assigned' for r in rows):flags.append('ambiguous_object_support')
    generic=bool(rows) and all(r.category in GENERIC_OBJECTS for r in rows)
    if generic:flags.append('non_discriminating_objects_only')
    return {'policy_version':EVIDENCE_POLICY_VERSION,'tier':'linked' if linked else 'graph_only',
        'verified':False,'native_links_confirmed':verified,'semantic_category_accuracy':'unmeasured','object_count':len(rows),'linked_observation_count':linked,
        'association_counts':dict(counts),'flags':tuple(flags),'only_generic_objects':generic,
        'objects':tuple({'native_id':r.native_id,'category':r.category,'membership':r.membership_status,
            'association':r.association_status,'evidence_count':r.evidence_count} for r in rows)}
