"""Gradient oracles for partial labels; run with detector26 interpreter."""
import pytest

torch = pytest.importorskip('torch')
pytest.importorskip('ultralytics')
from neusymnav.training.finetune import PartialBCE, masked_mask_loss


def test_unknown_anchor_and_unsupported_class_gradients_are_zero():
    logits=torch.zeros((1,3,3),requires_grad=True)
    targets=torch.zeros_like(logits);targets[0,1,0]=1
    loss=PartialBCE();loss.valid=torch.tensor([[False,False,True]])
    loss.classes=torch.tensor([True,True,False])
    loss(logits,targets).sum().backward()
    assert torch.count_nonzero(logits.grad[0,0]) == 0
    assert logits.grad[0,1,0] < 0
    assert logits.grad[0,1,1] == 0
    assert logits.grad[0,2,1] > 0
    assert torch.count_nonzero(logits.grad[...,2]) == 0


def test_mask_ignore_pixels_have_exact_zero_gradient():
    proto=torch.zeros((1,2,2),requires_grad=True)
    pred=torch.ones((1,1),requires_grad=True)
    valid=torch.tensor([[True,False],[False,False]])
    value=masked_mask_loss(torch.ones((1,2,2)),pred,proto,torch.tensor([[0.,0.,2.,2.]]),valid)
    value.backward()
    assert proto.grad[0,0,0] < 0
    assert torch.count_nonzero(proto.grad) == 1


def test_all_ignored_mask_has_finite_zero_loss():
    proto=torch.randn((1,2,2),requires_grad=True)
    loss=masked_mask_loss(torch.ones((1,2,2)),torch.ones((1,1)),proto,
                          torch.tensor([[0.,0.,2.,2.]]),torch.zeros((2,2),dtype=torch.bool))
    assert loss.item() == 0
    loss.backward()
    assert torch.count_nonzero(proto.grad) == 0


def test_ignore_resampling_matches_pil_instance_pixel_centers():
    import numpy as np
    from PIL import Image
    from torch.nn import functional as F
    raw=np.zeros((4,4),np.uint8);raw[2,2]=1
    ids=np.array(Image.fromarray(raw).resize((1,1),Image.Resampling.NEAREST))
    aligned=F.interpolate(torch.from_numpy(raw)[None,None].float(),(1,1),mode='nearest-exact')
    assert ids[0,0] == aligned.item() == 1
    assert F.interpolate(torch.from_numpy(raw)[None,None].float(),(1,1),mode='nearest').item() == 0


def test_partial_ap_eligibility_is_independent_for_box_and_mask():
    from neusymnav.training.finetune import metric_eligibility
    b,m=metric_eligibility([.1,.1,.8],[.1,.1,.8],[[.1],[.8],[.1]],
                          [[.8],[.1],[.1]],[[True],[True],[True]])
    assert b.tolist()==[False,True,True]
    assert m.tolist()==[True,False,True]
    b,m=metric_eligibility([0.],[0.],[[1.]],[[1.]],[[False]])
    assert not b.any() and not m.any()
