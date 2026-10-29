"""Fail-closed runtime health; worker errors are terminal, never silent retries."""
from threading import RLock


class Health:
    def __init__(self,actual_profile):
        self.lock=RLock();self.profile=actual_profile;self.failures={};self.replay_required=False
        self.counts=dict(semantic_stale=0,inference_start_stale=0,depth_stale=0,
                         rejected=0,nav_replaced=0,publication_mismatch=0)

    def fail(self,worker,error):
        with self.lock:
            self.failures[worker]=f'{type(error).__name__}: {error}'
            self.replay_required=True

    def increment(self,key):
        with self.lock:self.counts[key]=self.counts.get(key,0)+1

    def snapshot(self):
        with self.lock:return dict(actual_profile=self.profile,failed=dict(self.failures),replay_required=self.replay_required,counts=dict(self.counts))
