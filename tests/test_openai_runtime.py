import json
from pathlib import Path
import pytest
from test_object_identity import owner,commit
from test_projection import scene
from neusymnav.runtime.configuration import load_config

PREPROCESS='openai-clip-vit-b-32-eval-224-maskbboxpad20-v1'

def profile(tmp_path):
 d=json.loads(Path('configs/p10/demo-yoloe26m-conceptgraphs-gpu-00861.json').read_text())
 d.update(profile='appearance',appearance_mode='openai_clip',worker=dict(checkpoint_format='openai_jit',model_name='ViT-B-32',preprocessing_id=PREPROCESS,crop_recipe_id='mask-tight-xyxy+20px-clipped+PIL-float-edge-rounding-v1',feature_dimension=512,device='cpu',pretrained=None,state_dict_strict=True))
 p=tmp_path/'profile.json';p.write_text(json.dumps(d));return p,d

def test_openai_runtime_recipe_is_explicit_and_backend_pair_checked(tmp_path):
 p,d=profile(tmp_path)
 assert load_config(p).data['worker']['checkpoint_format']=='openai_jit'
 d['worker']['checkpoint_format']='safetensors';p.write_text(json.dumps(d))
 with pytest.raises(ValueError,match='appearance|checkpoint'):load_config(p)

def test_openai_owner_uses_appearance_and_pins_mode_on_restart(tmp_path):
 with owner(tmp_path,appearance_mode='openai_clip') as o:
  commit(o,scene());assert o._engine.association_mode=='geometry_appearance'
 with owner(tmp_path,appearance_mode='openai_clip') as o:assert len(o.snapshot().objects)==1
 with pytest.raises(ValueError,match='appearance profile mismatch'):owner(tmp_path,appearance_mode='openclip')


def test_real_encoder_nested_status_can_be_exported_as_runtime_json():
 from types import MappingProxyType
 from neusymnav.runtime.launcher import _EncoderMetadata
 class Encoder:
  space_metadata=MappingProxyType({'runtime':{'openai_clip':'1.0'}})
  last_status=MappingProxyType({'status':'available','detections':MappingProxyType({'0':MappingProxyType({'status':'available'})})})
  def encode(self,obs,batch):return object()
 sink={};wrapper=_EncoderMetadata(Encoder(),sink)
 wrapper.encode(None,None)
 encoded=json.loads(json.dumps(sink))
 assert encoded['appearance']['last_status']['detections']['0']['status']=='available'
