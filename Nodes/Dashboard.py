import math
from ..components.tree import TREE_DASHBOARD
from ..components.tree import PRIMERE_ROOT
from ..components.tree import TREE_DEPRECATED
import comfy.samplers
import folder_paths
import nodes
import torch
import torch.nn.functional as F
from .modules.latent_noise import PowerLawNoise
import random
import os
import tomli
from .modules.adv_encode import advanced_encode, advanced_encode_XL
from nodes import MAX_RESOLUTION
from ..components import utility
from pathlib import Path
import re
import requests
from ..components import hypernetwork
from ..components import clipping
import comfy.sd
import comfy.utils
from ..utils import comfy_dir
import comfy_extras.nodes_model_advanced as nodes_model_advanced
import comfy_extras.nodes_upscale_model as nodes_upscale_model
from comfy import model_management
from datetime import datetime

class PrimereSamplers:
    CATEGORY = TREE_DEPRECATED
    RETURN_TYPES = (comfy.samplers.KSampler.SAMPLERS, comfy.samplers.KSampler.SCHEDULERS)
    RETURN_NAMES = ("SAMPLER_NAME", "SCHEDULER_NAME")
    FUNCTION = "get_sampler"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "sampler_name": (comfy.samplers.KSampler.SAMPLERS,),
                "scheduler_name": (comfy.samplers.KSampler.SCHEDULERS,)
            }
        }

    def get_sampler(self, sampler_name, scheduler_name):
        return sampler_name, scheduler_name

class PrimereSamplersSteps:
    CATEGORY = TREE_DASHBOARD
    RETURN_TYPES = (comfy.samplers.KSampler.SAMPLERS, comfy.samplers.KSampler.SCHEDULERS, "INT", "FLOAT")
    RETURN_NAMES = ("SAMPLER_NAME", "SCHEDULER_NAME", "STEPS", "CFG")
    FUNCTION = "get_sampler_step"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "sampler_name": (comfy.samplers.KSampler.SAMPLERS,),
                "scheduler_name": (comfy.samplers.KSampler.SCHEDULERS,),
                "steps": ("INT", {"default": 12, "min": 1, "max": 1000, "step": 1}),
                "cfg": ("FLOAT", {"default": 7, "min": 0.1, "max": 100, "step": 0.01}),
            }
        }

    def get_sampler_step(self, sampler_name, scheduler_name, steps = 12, cfg = 7):
        return sampler_name, scheduler_name, steps, round(cfg, 2)

class PrimereVAE:
    RETURN_TYPES = ("VAE_NAME",)
    RETURN_NAMES = ("VAE_NAME",)
    FUNCTION = "load_vae_list"
    CATEGORY = TREE_DASHBOARD

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "vae_model": (folder_paths.get_filename_list("vae"),)
            },
        }

    def load_vae_list(self, vae_model):
        return vae_model,

class PrimereCKPT:
    RETURN_TYPES = ("CHECKPOINT_NAME", "STRING",)
    RETURN_NAMES = ("MODEL_NAME", "MODEL_VERSION",)
    FUNCTION = "load_ckpt_list"
    CATEGORY = TREE_DASHBOARD

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "base_model": (folder_paths.get_filename_list("checkpoints"),),
            },
        }

    def load_ckpt_list(self, base_model):
        modelname_only = Path(base_model).stem
        model_version = utility.get_value_from_cache('model_version', modelname_only)
        if model_version is None:
            LOADED_CHECKPOINT = nodes.CheckpointLoaderSimple.load_checkpoint(self, base_model)
            model_version = utility.getCheckpointVersion(LOADED_CHECKPOINT[0])
            utility.add_value_to_cache('model_version', modelname_only, model_version)

        return (base_model, model_version)

class PrimereVAELoader:
    RETURN_TYPES = ("VAE",)
    RETURN_NAMES = ("VAE",)
    FUNCTION = "load_primere_vae"
    CATEGORY = TREE_DASHBOARD

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "vae_name": ("VAE_NAME",),
                "baked_vae": ("VAE",)
            },
        }

    def load_primere_vae(self, vae_name, baked_vae,):
        if (vae_name == 'Baked VAE'):
            return (baked_vae,)

        if (vae_name == 'External VAE'):
            vae_name = folder_paths.get_filename_list("vae")[0]

        return nodes.VAELoader.load_vae(self, vae_name)

class PrimereLCMSelector:
    RETURN_TYPES = (comfy.samplers.KSampler.SAMPLERS, comfy.samplers.KSampler.SCHEDULERS, "INT", "FLOAT", "STRING")
    RETURN_NAMES = ("SAMPLER_NAME", "SCHEDULER_NAME", "STEPS", "CFG", "MODEL_CONCEPT")
    FUNCTION = "select_lcm_mode"
    CATEGORY = TREE_DEPRECATED

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "use_lcm": ("BOOLEAN", {"default": False}),
                "sampler_name": (comfy.samplers.KSampler.SAMPLERS, {"forceInput": True, "default": "euler"}),
                "scheduler_name": (comfy.samplers.KSampler.SCHEDULERS, {"forceInput": True, "default": "normal"}),
                "lcm_sampler_name": (comfy.samplers.KSampler.SAMPLERS, {"forceInput": True, "default": "lcm"}),
                "lcm_scheduler_name": (comfy.samplers.KSampler.SCHEDULERS, {"forceInput": True, "default": "sgm_uniform"}),
                "cfg_scale": ('FLOAT', {"forceInput": True, "default": 7}),
                "steps": ('INT', {"forceInput": True, "default": 12}),
                "lcm_cfg_scale": ('FLOAT', {"forceInput": True, "default": 1.2}),
                "lcm_steps": ('INT', {"forceInput": True, "default": 6}),
            },
        }

    def select_lcm_mode(self, use_lcm = False, sampler_name = 'euler', scheduler_name = 'normal', lcm_sampler_name = 'lcm', lcm_scheduler_name = 'sgm_uniform', cfg_scale = 7, steps = 12, lcm_cfg_scale = 1.2, lcm_steps = 6):
        model_concept = "Normal"
        if use_lcm == True:
            sampler_name = lcm_sampler_name
            scheduler_name = lcm_scheduler_name
            steps = lcm_steps
            cfg_scale = lcm_cfg_scale
            model_concept = "LCM"

        return (sampler_name, scheduler_name, steps, cfg_scale, model_concept,)

class PrimereModelConceptSelector:
    RETURN_TYPES = (comfy.samplers.KSampler.SAMPLERS, comfy.samplers.KSampler.SCHEDULERS, "INT", "FLOAT", "STRING", "STRING", "INT", "STRING", "STRING", "STRING", "STRING", "STRING", "INT")
    RETURN_NAMES = ("SAMPLER_NAME", "SCHEDULER_NAME", "STEPS", "CFG", "MODEL_CONCEPT", "LIGHTNING_SELECTOR", "LIGHTNING_MODEL_STEP", "CASCADE_STAGE_A", "CASCADE_STAGE_B", "CASCADE_STAGE_C", "CASCADE_CLIP", "HYPER-SD_SELECTOR", "HYPER-SD_MODEL_STEP")
    FUNCTION = "select_model_concept"
    CATEGORY = TREE_DASHBOARD

    UNETLIST = folder_paths.get_filename_list("unet")
    VAELIST = folder_paths.get_filename_list("vae")
    CLIPLIST = folder_paths.get_filename_list("clip")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "normal_sampler_name": (comfy.samplers.KSampler.SAMPLERS, {"forceInput": True, "default": "euler"}),
                "normal_scheduler_name": (comfy.samplers.KSampler.SCHEDULERS, {"forceInput": True, "default": "normal"}),
                "normal_cfg_scale": ('FLOAT', {"forceInput": True, "default": 7}),
                "normal_steps": ('INT', {"forceInput": True, "default": 12}),

                "model_concept": (["Normal", "LCM", "Turbo", "Cascade", "Lightning", "Playground", "Hyper-SD"], {"default": "Normal"}),
                "lightning_selector": (["UNET", "LORA", "SAFETENSOR", "CUSTOM"], {"default": "SAFETENSOR"}),
                "lightning_model_step": ([1, 2, 4, 8], {"default": 8}),
                "lightning_sampler": ("BOOLEAN", {"default": False, "label_on": "Set by model", "label_off": "Custom (external)"}),

                "hypersd_selector": (["UNET", "LORA"], {"default": "LORA"}),
                "hypersd_model_step": ([1, 2, 4, 8], {"default": 8}),
                "hypersd_sampler": ("BOOLEAN", {"default": False, "label_on": "Set by model", "label_off": "Custom (external)"}),

                "cascade_stage_a": (cls.VAELIST,),
                "cascade_stage_b": (cls.UNETLIST,),
                "cascade_stage_c": (cls.UNETLIST,),
                "cascade_clip": (cls.CLIPLIST,),

                # "playground_sigma_max": ("FLOAT", {"default": 120.0, "min": 0.0, "max": 1000.0, "step": 0.001, "round": False}),
                # "playground_sigma_min": ("FLOAT", {"default": 0.002, "min": 0.0, "max": 1000.0, "step": 0.001, "round": False}),
            },
            "optional": {
                "lcm_sampler_name": (comfy.samplers.KSampler.SAMPLERS, {"forceInput": True, "default": "lcm"}),
                "lcm_scheduler_name": (comfy.samplers.KSampler.SCHEDULERS, {"forceInput": True, "default": "sgm_uniform"}),
                "lcm_cfg_scale": ('FLOAT', {"forceInput": True, "default": 1.2}),
                "lcm_steps": ('INT', {"forceInput": True, "default": 6}),

                "turbo_sampler_name": (comfy.samplers.KSampler.SAMPLERS, {"forceInput": True, "default": "dpmpp_sde"}),
                "turbo_scheduler_name": (comfy.samplers.KSampler.SCHEDULERS, {"forceInput": True, "default": "normal"}),
                "turbo_cfg_scale": ('FLOAT', {"forceInput": True, "default": 1.15}),
                "turbo_steps": ('INT', {"forceInput": True, "default": 2}),

                "cascade_sampler_name": (comfy.samplers.KSampler.SAMPLERS, {"forceInput": True, "default": "euler_ancestral"}),
                "cascade_scheduler_name": (comfy.samplers.KSampler.SCHEDULERS, {"forceInput": True, "default": "simple"}),
                "cascade_cfg_scale": ('FLOAT', {"forceInput": True, "default": 4}),
                "cascade_steps": ('INT', {"forceInput": True, "default": 20}),

                "lightning_sampler_name": (comfy.samplers.KSampler.SAMPLERS, {"forceInput": True, "default": "dpmpp_sde"}),
                "lightning_scheduler_name": (comfy.samplers.KSampler.SCHEDULERS, {"forceInput": True, "default": "simple"}),
                "lightning_cfg_scale": ('FLOAT', {"forceInput": True, "default": 1.2}),
                "lightning_steps": ('INT', {"forceInput": True, "default": 6}),

                "playground_sampler_name": (comfy.samplers.KSampler.SAMPLERS, {"forceInput": True, "default": "euler"}),
                "playground_scheduler_name": (comfy.samplers.KSampler.SCHEDULERS, {"forceInput": True, "default": "normal"}),
                "playground_cfg_scale": ('FLOAT', {"forceInput": True, "default": 3}),
                "playground_steps": ('INT', {"forceInput": True, "default": 50}),

                "hypersd_sampler_name": (comfy.samplers.KSampler.SAMPLERS, {"forceInput": True, "default": "dpmpp_sde"}),
                "hypersd_scheduler_name": (comfy.samplers.KSampler.SCHEDULERS, {"forceInput": True, "default": "simple"}),
                "hypersd_cfg_scale": ('FLOAT', {"forceInput": True, "default": 1.2}),
                "hypersd_steps": ('INT', {"forceInput": True, "default": 6}),
            }
        }

    def select_model_concept(self, cascade_stage_a, cascade_stage_b, cascade_stage_c, cascade_clip,
                             model_concept = 'Normal',
                             lightning_selector = "SAFETENSOR", lightning_model_step = 8, lightning_sampler = False,
                             hypersd_selector="LORA", hypersd_model_step=8, hypersd_sampler=False,
                             normal_sampler_name = 'euler', normal_scheduler_name = 'normal', normal_cfg_scale = 7, normal_steps = 12,
                             lcm_sampler_name = 'lcm', lcm_scheduler_name = 'sgm_uniform', lcm_cfg_scale = 1.2, lcm_steps = 6,
                             turbo_sampler_name = 'dpmpp_sde', turbo_scheduler_name = "karras", turbo_cfg_scale = 1.15, turbo_steps = 2,
                             cascade_sampler_name = 'euler_ancestral', cascade_scheduler_name = "simple", cascade_cfg_scale = 4, cascade_steps = 20,
                             lightning_sampler_name = 'dpmpp_sde', lightning_scheduler_name = "simple", lightning_cfg_scale = 1.2, lightning_steps = 6,
                             playground_sampler_name = 'euler', playground_scheduler_name = 'normal', playground_cfg_scale = 3, playground_steps = 50,
                             hypersd_sampler_name = 'dpmpp_sde', hypersd_scheduler_name = "simple", hypersd_cfg_scale = 1.2, hypersd_steps = 6,):

        sampler_name = normal_sampler_name
        scheduler_name = normal_scheduler_name
        steps = normal_steps
        cfg_scale = normal_cfg_scale

        match model_concept:
            case 'Normal':
                sampler_name = normal_sampler_name
                scheduler_name = normal_scheduler_name
                steps = normal_steps
                cfg_scale = normal_cfg_scale

            case 'LCM':
                sampler_name = lcm_sampler_name
                scheduler_name = lcm_scheduler_name
                steps = lcm_steps
                cfg_scale = lcm_cfg_scale

            case 'Turbo':
                sampler_name = turbo_sampler_name
                scheduler_name = turbo_scheduler_name
                steps = turbo_steps
                cfg_scale = turbo_cfg_scale

            case 'Cascade':
                sampler_name = cascade_sampler_name
                scheduler_name = cascade_scheduler_name
                steps = cascade_steps
                cfg_scale = cascade_cfg_scale

            case 'Lightning':
                if lightning_sampler == False:
                    sampler_name = lightning_sampler_name
                    scheduler_name = lightning_scheduler_name
                    steps = lightning_steps
                    cfg_scale = lightning_cfg_scale
                else:
                    sampler_name = 'euler'
                    scheduler_name = 'sgm_uniform'
                    steps = lightning_model_step
                    cfg_scale = 1

            case 'Playground':
                sampler_name = playground_sampler_name
                scheduler_name = playground_scheduler_name
                steps = playground_steps
                cfg_scale = playground_cfg_scale

            case 'Hyper-SD':
                if hypersd_sampler == True and hypersd_selector == 'UNET':
                    sampler_name = 'lcm'
                    scheduler_name = hypersd_scheduler_name
                    steps = 1
                    cfg_scale = 1
                elif hypersd_sampler == False:
                    sampler_name = hypersd_sampler_name
                    scheduler_name = hypersd_scheduler_name
                    steps = hypersd_steps
                    cfg_scale = hypersd_cfg_scale
                else:
                    sampler_name = 'euler'
                    scheduler_name = 'sgm_uniform'
                    steps = hypersd_model_step
                    cfg_scale = 1

        if model_concept != 'Lightning':
            lightning_selector = None
            lightning_model_step = None

        if model_concept != 'Hyper-SD':
            hypersd_selector = None
            hypersd_model_step = None

        if model_concept != 'Cascade':
            cascade_stage_a = None
            cascade_stage_b = None
            cascade_stage_c = None
            cascade_clip = None

        return (sampler_name, scheduler_name, steps, round(cfg_scale, 2), model_concept, lightning_selector, lightning_model_step, cascade_stage_a, cascade_stage_b, cascade_stage_c, cascade_clip, hypersd_selector, hypersd_model_step,)

class PrimereCKPTLoader:
    RETURN_TYPES = ("MODEL", "CLIP", "VAE", "STRING",)
    RETURN_NAMES = ("MODEL", "CLIP", "VAE", "MODEL_VERSION")
    FUNCTION = "load_primere_ckpt"
    CATEGORY = TREE_DASHBOARD

    def __init__(self):
        self.loaded_lora = None

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "ckpt_name": ("CHECKPOINT_NAME",),
                "use_yaml": ("BOOLEAN", {"default": False}),
                "strength_lcm_model": ("FLOAT", {"default": 1.0, "min": -20.0, "max": 20.0, "step": 0.01}),
                "strength_lcm_clip": ("FLOAT", {"default": 1.0, "min": -20.0, "max": 20.0, "step": 0.01}),
            },
            "optional": {
                "model_concept": ("STRING", {"default": "Normal", "forceInput": True}),
                "concept_data": ("TUPLE", {"default": None, "forceInput": True}),
                "loaded_model": ('MODEL', {"forceInput": True, "default": None}),
                "loaded_clip": ('CLIP', {"forceInput": True, "default": None}),
                "loaded_vae": ('VAE', {"forceInput": True, "default": None}),
            },
        }

    def load_primere_ckpt(self, ckpt_name, use_yaml, strength_lcm_model, strength_lcm_clip,
                          model_concept = "Normal", concept_data = None,
                          lightning_selector = 'SAFETENSOR', lightning_model_step = 8,
                          hypersd_selector = 'LORA', hypersd_model_step = 8,
                          cascade_stage_a = None, cascade_stage_b = None, cascade_stage_c = None, cascade_clip = None,
                          loaded_model = None, loaded_clip = None, loaded_vae = None):

        playground_sigma_max = 120
        playground_sigma_min = 0.002

        if concept_data is not None:
            if 'lightning_selector' in concept_data:
                lightning_selector = concept_data['lightning_selector']
            if 'lightning_model_step' in concept_data:
                lightning_model_step = concept_data['lightning_model_step']

            if 'hypersd_selector' in concept_data:
                hypersd_selector = concept_data['hypersd_selector']
            if 'hypersd_model_step' in concept_data:
                hypersd_model_step = concept_data['hypersd_model_step']

            if 'cascade_stage_a' in concept_data:
                cascade_stage_a = concept_data['cascade_stage_a']
            if 'cascade_stage_b' in concept_data:
                cascade_stage_b = concept_data['cascade_stage_b']
            if 'cascade_stage_c' in concept_data:
                cascade_stage_c = concept_data['cascade_stage_c']
            if 'cascade_clip' in concept_data:
                cascade_clip = concept_data['cascade_clip']

        if model_concept == "Cascade" and cascade_stage_a is not None and cascade_stage_b is not None and cascade_stage_c is not None and cascade_clip is not None:
            MODEL_VERSION = 'SDXL_2048'

            OUTPUT_CLIP_CAS = nodes.CLIPLoader.load_clip(self, cascade_clip, 'stable_cascade')[0]
            OUTPUT_VAE_CAS = nodes.VAELoader.load_vae(self, cascade_stage_a)[0]
            MODEL_C_CAS = nodes.UNETLoader.load_unet(self, cascade_stage_c)[0]
            MODEL_B_CAS = nodes.UNETLoader.load_unet(self, cascade_stage_b)[0]

            OUTPUT_MODEL_CAS = [MODEL_B_CAS, MODEL_C_CAS]
            return (OUTPUT_MODEL_CAS,) + (OUTPUT_CLIP_CAS,) + (OUTPUT_VAE_CAS,) + (MODEL_VERSION,)

        if model_concept == "Hyper-SD" and hypersd_selector == 'UNET':
            MODEL_VERSION = 'SDXL_2048'
            ModelConceptChanges = utility.ModelConceptNames(ckpt_name, model_concept, lightning_selector, lightning_model_step, hypersd_selector, hypersd_model_step, MODEL_VERSION)
            lora_name = ModelConceptChanges['lora_name']
            unet_name = ModelConceptChanges['unet_name']
            hyperModeValid = ModelConceptChanges['hyperModeValid']
            OUTPUT_MODEL = utility.LightningConceptModel(self, model_concept, hyperModeValid, hypersd_selector, hypersd_model_step, None, lora_name, unet_name)
            return (OUTPUT_MODEL[0],) + (OUTPUT_MODEL[1],) + (OUTPUT_MODEL[2],) + (MODEL_VERSION,)

        ModelConceptChanges = utility.ModelConceptNames(ckpt_name, model_concept, lightning_selector, lightning_model_step, hypersd_selector, hypersd_model_step)
        ckpt_name = ModelConceptChanges['ckpt_name']
        lora_name = ModelConceptChanges['lora_name']
        unet_name = ModelConceptChanges['unet_name']
        lightningModeValid = ModelConceptChanges['lightningModeValid']

        path = Path(ckpt_name)
        ModelName = path.stem
        ModelConfigPath = path.parent.joinpath(ModelName + '.yaml')
        ModelConfigFullPath = Path(folder_paths.models_dir).joinpath('checkpoints').joinpath(ModelConfigPath)

        if (loaded_model is not None and loaded_clip is not None and loaded_vae is not None):
            LOADED_CHECKPOINT = []
            LOADED_CHECKPOINT.insert(0, loaded_model)
            LOADED_CHECKPOINT.insert(1, loaded_clip)
            LOADED_CHECKPOINT.insert(2, loaded_vae)
        else:
            if (os.path.isfile(ModelConfigFullPath) and use_yaml == True):
                ckpt_path = folder_paths.get_full_path("checkpoints", ckpt_name)
                print(ModelName + '.yaml file found and loading...')
                try:
                    LOADED_CHECKPOINT = comfy.sd.load_checkpoint(ModelConfigFullPath, ckpt_path, True, True, None, None, None)
                except Exception:
                    LOADED_CHECKPOINT = nodes.CheckpointLoaderSimple.load_checkpoint(self, ckpt_name)
            else:
                LOADED_CHECKPOINT = nodes.CheckpointLoaderSimple.load_checkpoint(self, ckpt_name)

        OUTPUT_MODEL = LOADED_CHECKPOINT[0]
        OUTPUT_CLIP = LOADED_CHECKPOINT[1]

        MODEL_VERSION = utility.get_value_from_cache('model_version', ModelName)
        if MODEL_VERSION is None:
            MODEL_VERSION = utility.getCheckpointVersion(OUTPUT_MODEL)
            utility.add_value_to_cache('model_version', ModelName, MODEL_VERSION)

        hyperModeValid = False
        if model_concept == "Hyper-SD":
            ModelConceptChanges = utility.ModelConceptNames(ckpt_name, model_concept, lightning_selector, lightning_model_step, hypersd_selector, hypersd_model_step, MODEL_VERSION)
            # ckpt_name = ModelConceptChanges['ckpt_name']
            lora_name = ModelConceptChanges['lora_name']
            unet_name = ModelConceptChanges['unet_name']
            hyperModeValid = ModelConceptChanges['hyperModeValid']

        def lcm(self, model, zsnr=False):
            m = model.clone()

            # sampling_base = comfy.model_sampling.ModelSamplingDiscrete
            sampling_type = nodes_model_advanced.LCM
            sampling_base = utility.ModelSamplingDiscreteLCM

            class ModelSamplingAdvanced(sampling_base, sampling_type):
                pass

            model_sampling = ModelSamplingAdvanced()
            if zsnr:
                model_sampling.set_sigmas(nodes_model_advanced.rescale_zero_terminal_snr_sigmas(model_sampling.sigmas))

            m.add_object_patch("model_sampling", model_sampling)
            return m

        is_sdxl = 0
        match MODEL_VERSION:
            case 'SDXL_2048':
                is_sdxl = 1

        if model_concept == "LCM":
            SDXL_LORA = 'https://huggingface.co/latent-consistency/lcm-lora-sdxl/resolve/main/pytorch_lora_weights.safetensors?download=true'
            SD_LORA = 'https://huggingface.co/latent-consistency/lcm-lora-sdv1-5/resolve/main/pytorch_lora_weights.safetensors?download=true'
            DOWNLOADED_SD_LORA = os.path.join(PRIMERE_ROOT, 'Nodes', 'Downloads', 'lcm_lora_sd.safetensors')
            DOWNLOADED_SDXL_LORA = os.path.join(PRIMERE_ROOT, 'Nodes', 'Downloads', 'lcm_lora_sdxl.safetensors')

            if os.path.exists(DOWNLOADED_SD_LORA) == False:
                print('Downloading SD LCM LORA....')
                reqsdlcm = requests.get(SD_LORA, allow_redirects=True)
                if reqsdlcm.status_code == 200 and reqsdlcm.ok == True:
                    open(DOWNLOADED_SD_LORA, 'wb').write(reqsdlcm.content)
                else:
                    print('ERROR: Cannot dowload SD LCM Lora')

            if os.path.exists(DOWNLOADED_SDXL_LORA) == False:
                print('Downloading SDXL LCM LORA....')
                reqsdxllcm = requests.get(SDXL_LORA, allow_redirects=True)
                if reqsdxllcm.status_code == 200 and reqsdxllcm.ok == True:
                    open(DOWNLOADED_SDXL_LORA, 'wb').write(reqsdxllcm.content)
                else:
                    print('ERROR: Cannot dowload SDXL LCM Lora')

            if is_sdxl == 0:
                LORA_PATH = DOWNLOADED_SD_LORA
            else:
                LORA_PATH = DOWNLOADED_SDXL_LORA

            if os.path.exists(LORA_PATH) == True:
                if strength_lcm_model > 0 or strength_lcm_clip > 0:
                    print('LCM mode on')
                    lora = None

                    if self.loaded_lora is not None:
                        if self.loaded_lora[0] == LORA_PATH:
                            lora = self.loaded_lora[1]
                        else:
                            temp = self.loaded_lora
                            self.loaded_lora = None
                            del temp

                    if lora is None:
                        lora = comfy.utils.load_torch_file(LORA_PATH, safe_load=True)
                        self.loaded_lora = (LORA_PATH, lora)

                    MODEL_LORA, CLIP_LORA = comfy.sd.load_lora_for_models(OUTPUT_MODEL, OUTPUT_CLIP, lora, strength_lcm_model, strength_lcm_clip)

                    OUTPUT_MODEL = lcm(self, MODEL_LORA, False)
                    OUTPUT_CLIP = CLIP_LORA

        if model_concept == "Lightning" and lightningModeValid == True and loaded_model is None:
            OUTPUT_MODEL = utility.LightningConceptModel(self, model_concept, lightningModeValid, lightning_selector, lightning_model_step, OUTPUT_MODEL, lora_name, unet_name)

        if model_concept == "Hyper-SD" and hyperModeValid == True and loaded_model is None:
            OUTPUT_MODEL = utility.LightningConceptModel(self, model_concept, hyperModeValid, hypersd_selector, hypersd_model_step, OUTPUT_MODEL, lora_name, unet_name)

        if model_concept == "Playground":
            OUTPUT_MODEL = nodes_model_advanced.ModelSamplingContinuousEDM.patch(self, OUTPUT_MODEL, 'edm_playground_v2.5', playground_sigma_max, playground_sigma_min)[0]

        return (OUTPUT_MODEL,) + (OUTPUT_CLIP,) + (LOADED_CHECKPOINT[2],) + (MODEL_VERSION,)

class AnyType(str):
    def __ne__(self, __value: object) -> bool:
        return False

class PrimerePromptSwitch:
    any_typ = AnyType("*")

    RETURN_TYPES = (any_typ, any_typ, "INT", "TUPLE")
    RETURN_NAMES = ("PROMPT+", "PROMPT-", "SELECTED_INDEX", "PREFERRED")
    FUNCTION = "promptswitch"
    CATEGORY = TREE_DASHBOARD

    @classmethod
    def INPUT_TYPES(cls):
        any_typ = AnyType("*")

        return {
            "required": {
                "select": ("INT", {"default": 1, "min": 1, "max": 20, "step": 1}),
            },
            "optional": {
                "prompt_pos_1": (any_typ,),
                "prompt_neg_1": (any_typ,),
                "preferred_1": (any_typ,),
            },
        }

    def promptswitch(self, *args, **kwargs):
        selected_index = int(kwargs['select'])
        input_namep = f"prompt_pos_{selected_index}"
        input_namen = f"prompt_neg_{selected_index}"
        input_preferred = f"preferred_{selected_index}"

        if input_namep in kwargs:
            return (kwargs[input_namep], kwargs[input_namen], selected_index, kwargs[input_preferred])
        else:
            print(f"PrimerePromptSwitch: invalid select index (ignored)")
            return (None, None, selected_index, None)


class PrimereSeed:
    RETURN_TYPES = ("INT",)
    RETURN_NAMES = ("SEED",)
    FUNCTION = "seed"
    CATEGORY = TREE_DASHBOARD

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "seed": ("INT", {"default": -1, "min": -1125899906842624, "max": 1125899906842624}),
            }
        }

    def seed(self, seed = -1):
      return (seed,)

class PrimereFractalLatent:

    @classmethod
    def INPUT_TYPES(cls):
        pln = PowerLawNoise('cpu')
        return {
            "required": {
                "width": ("INT", {"default": 512, "max": 8192, "min": 64, "forceInput": True}),
                "height": ("INT", {"default": 512, "max": 8192, "min": 64, "forceInput": True}),
                "rand_noise_type": ("BOOLEAN", {"default": False}),
                "noise_type": (pln.get_noise_types(),),
                "rand_alpha_exponent": ("BOOLEAN", {"default": True}),
                "alpha_exponent": ("FLOAT", {"default": 1.0, "max": 12.0, "min": -12.0, "step": 0.001}),
                "alpha_exp_rand_min": ("FLOAT", {"default": 0.5, "max": 12.0, "min": -12.0, "step": 0.001}),
                "alpha_exp_rand_max": ("FLOAT", {"default": 1.5, "max": 12.0, "min": -12.0, "step": 0.001}),
                "rand_modulator": ("BOOLEAN", {"default": True}),
                "modulator": ("FLOAT", {"default": 1.0, "max": 2.0, "min": 0.1, "step": 0.01}),
                "modulator_rand_min": ("FLOAT", {"default": 0.8, "max": 2.0, "min": 0.1, "step": 0.01}),
                "modulator_rand_max": ("FLOAT", {"default": 1.4, "max": 2.0, "min": 0.1, "step": 0.01}),
                "noise_seed": ("INT", {"default": 0, "min": -1, "max": 0xffffffffffffffff, "forceInput": True}),
                "rand_device": ("BOOLEAN", {"default": False}),
                "device": (["cpu", "cuda"],),
                "expand_random_limits": ("BOOLEAN", {"default": False, "label_on": "ON", "label_off": "OFF"}),
            },
            "optional": {
                "optional_vae": ("VAE",),
            }
        }

    RETURN_TYPES = ("LATENT", "IMAGE")
    RETURN_NAMES = ("LATENTS", "PREVIEWS")
    FUNCTION = "primere_latent_noise"
    CATEGORY = TREE_DASHBOARD

    def IS_CHANGED(self, **kwargs):
        if kwargs['expand_random_limits'] == True or kwargs['rand_noise_type'] == True or kwargs['rand_device'] == True or kwargs['rand_alpha_exponent'] == True or kwargs['rand_modulator'] == True:
            return float('NaN')

    def primere_latent_noise(self, width, height, rand_noise_type, noise_type, rand_alpha_exponent, alpha_exponent, alpha_exp_rand_min, alpha_exp_rand_max, rand_modulator, modulator, modulator_rand_min, modulator_rand_max, noise_seed, rand_device, device, optional_vae = None, expand_random_limits = False, fine_variation_strength = 0):
        if expand_random_limits == True:
            rand_device = True
            rand_alpha_exponent = True
            rand_modulator = True
            rand_noise_type = True
            alpha_exp_rand_min = -12.00
            alpha_exp_rand_max = 7.00
            modulator_rand_min = 0.10
            modulator_rand_max = 2.00

        if rand_noise_type == True:
            pln = PowerLawNoise(device)
            noise_type = random.choice(pln.get_noise_types())

        if rand_device == True:
            device = random.choice(["cpu", "cuda"])

        if expand_random_limits == True and (noise_type == 'white' or noise_type == 'violet'):
            alpha_exp_rand_min = 0.00

        power_law = PowerLawNoise(device = device)

        if rand_alpha_exponent == True:
            alpha_exponent = round(random.uniform(alpha_exp_rand_min, alpha_exp_rand_max), 3)

        if rand_modulator == True:
            modulator = round(random.uniform(modulator_rand_min, modulator_rand_max), 2)

        tensors = power_law(1, width, height, scale = 1, alpha = alpha_exponent, modulator = modulator, noise_type = noise_type, seed = noise_seed)
        alpha_channel = torch.ones((1, height, width, 1), dtype = tensors.dtype, device = "cpu")
        tensors = torch.cat((tensors, alpha_channel), dim = 3)

        if optional_vae is None:
            latents = tensors.permute(0, 3, 1, 2)
            latents = F.interpolate(latents, size=((height // 8), (width // 8)), mode = 'nearest-exact')
            return {'samples': latents}, tensors

        encoder = nodes.VAEEncode()
        latents = []
        for tensor in tensors:
            tensor = tensor.unsqueeze(0)
            latents.append(encoder.encode(optional_vae, tensor)[0]['samples'])

        latents = torch.cat(latents)
        return {'samples': latents}, tensors

class PrimereCLIP:
    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("COND+", "COND-", "PROMPT+", "PROMPT-", "PROMPT L+", "PROMPT L-")
    FUNCTION = "clip_encode"
    CATEGORY = TREE_DASHBOARD

    @staticmethod
    def get_default_neg(toml_path: str):
        with open(toml_path, "rb") as f:
            style_def_neg = tomli.load(f)
        return style_def_neg
    @ classmethod
    def INPUT_TYPES(cls):
        DEF_TOML_DIR = os.path.join(PRIMERE_ROOT, 'Toml')
        cls.default_neg = cls.get_default_neg(os.path.join(DEF_TOML_DIR, "default_neg.toml"))
        cls.default_pos = cls.get_default_neg(os.path.join(DEF_TOML_DIR, "default_pos.toml"))

        return {
            "required": {
                "clip": ("CLIP", ),
                "model_version": ("STRING", {"default": 'BaseModel_1024', "forceInput": True}),
                "positive_prompt": ("STRING", {"forceInput": True}),
                "negative_prompt": ("STRING", {"forceInput": True}),
                # "custom_clip_model": (['None'] + sorted(cls.CLIPLIST),),
                "use_long_clip": ("BOOLEAN", {"default": True}),
                "last_layer": ("INT", {"default": 0, "min": -24, "max": 0, "step": 1}),
                "negative_strength": ("FLOAT", {"default": 1.2, "min": 0.0, "max": 10.0, "step": 0.01}),
                "use_int_style": ("BOOLEAN", {"default": False}),
                "int_style_pos": (['None'] + sorted(list(cls.default_pos.keys())),),
                "int_style_pos_strength": ("FLOAT", {"default": 1, "min": 0.0, "max": 10.0, "step": 0.01}),
                "int_style_neg": (['None'] + sorted(list(cls.default_neg.keys())),),
                "int_style_neg_strength": ("FLOAT", {"default": 1, "min": 0.0, "max": 10.0, "step": 0.01}),
                "adv_encode": ("BOOLEAN", {"default": False}),
                "token_normalization": (["none", "mean", "length", "length+mean"],),
                "weight_interpretation": (["comfy", "A1111", "compel", "comfy++", "down_weight"],),
            },
            "optional": {
                "model_concept": ("STRING", {"default": "Normal", "forceInput": True}),
                "model_keywords": ("MODEL_KEYWORD", {"forceInput": True}),
                "lora_keywords": ("MODEL_KEYWORD", {"forceInput": True}),
                "lycoris_keywords": ("MODEL_KEYWORD", {"forceInput": True}),
                "embedding_pos": ("EMBEDDING", {"forceInput": True}),
                "embedding_neg": ("EMBEDDING", {"forceInput": True}),

                "opt_pos_prompt": ("STRING", {"forceInput": True}),
                "opt_pos_strength": ("FLOAT", {"default": 1, "min": 0.0, "max": 10.0, "step": 0.01}),
                "opt_neg_prompt": ("STRING", {"forceInput": True}),
                "opt_neg_strength": ("FLOAT", {"default": 1, "min": 0.0, "max": 10.0, "step": 0.01}),

                "style_position": ("BOOLEAN", {"default": False, "label_on": "Top", "label_off": "Bottom"}),
                "style_pos_prompt": ("STRING", {"forceInput": True}),
                "style_pos_strength": ("FLOAT", {"default": 1, "min": 0.0, "max": 10.0, "step": 0.01}),
                "style_neg_prompt": ("STRING", {"forceInput": True}),
                "style_neg_strength": ("FLOAT", {"default": 1, "min": 0.0, "max": 10.0, "step": 0.01}),

                "sdxl_positive_l": ("STRING", {"forceInput": True}),
                "sdxl_negative_l": ("STRING", {"forceInput": True}),
                "copy_prompt_to_l": ("BOOLEAN", {"default": True}),
                "sdxl_l_strength": ("FLOAT", {"default": 1, "min": 0.0, "max": 10.0, "step": 0.01}),
                "width": ("INT", {"default": 1024.0, "min": 0, "max": MAX_RESOLUTION, "forceInput": True}),
                "height": ("INT", {"default": 1024.0, "min": 0, "max": MAX_RESOLUTION, "forceInput": True}),
            }
        }

    def clip_encode(self, clip, use_long_clip, last_layer, negative_strength, int_style_pos_strength, int_style_neg_strength, opt_pos_strength, opt_neg_strength, style_pos_strength, style_neg_strength, int_style_pos, int_style_neg, adv_encode, token_normalization, weight_interpretation, sdxl_l_strength, copy_prompt_to_l = True, width = 1024, height = 1024, positive_prompt = "", negative_prompt = "", custom_clip_model = 'None', model_keywords = None, lora_keywords = None, lycoris_keywords = None, embedding_pos = None, embedding_neg = None, opt_pos_prompt = "", opt_neg_prompt = "", style_position = False, style_neg_prompt = "", style_pos_prompt = "", sdxl_positive_l = "", sdxl_negative_l = "", use_int_style = False, model_version = "BaseModel_1024", model_concept = "Normal"):
        if model_concept == 'Cascade' or model_concept == 'Turbo':
            model_version = 'SDXL_2048'

        is_sdxl = 0
        match model_version:
            case 'SDXL_2048':
                is_sdxl = 1

        additional_positive = int_style_pos
        additional_negative = int_style_neg
        if int_style_pos == 'None' or use_int_style == False:
            additional_positive = None
        if int_style_neg == 'None' or use_int_style == False:
            additional_negative = None

        if use_int_style == True:
            if int_style_pos != 'None':
                additional_positive = self.default_pos[int_style_pos]['positive'].strip(' ,;')
            if int_style_neg != 'None':
                additional_negative = self.default_neg[int_style_neg]['negative'].strip(' ,;')

        additional_positive = f'({additional_positive}:{int_style_pos_strength:.2f})' if additional_positive is not None and additional_positive != '' else ''
        additional_negative = f'({additional_negative}:{int_style_neg_strength:.2f})' if additional_negative is not None and additional_negative != '' else ''

        negative_prompt = f'({negative_prompt}:{negative_strength:.2f})' if negative_prompt is not None and negative_prompt.strip(' ,;') != '' else ''

        opt_pos_prompt = f'({opt_pos_prompt}:{opt_pos_strength:.2f})' if opt_pos_prompt is not None and opt_pos_prompt.strip(' ,;') != '' else ''
        opt_neg_prompt = f'({opt_neg_prompt}:{opt_neg_strength:.2f})' if opt_neg_prompt is not None and opt_neg_prompt.strip(' ,;') != '' else ''

        if style_pos_strength != 1:
            style_pos_prompt = f'({style_pos_prompt}:{style_pos_strength:.2f})' if style_pos_prompt is not None and style_pos_prompt.strip(' ,;') != '' else ''
        else:
            style_pos_prompt = f'{style_pos_prompt}' if style_pos_prompt is not None and style_pos_prompt.strip(' ,;') != '' else ''

        if style_neg_prompt != 1:
            style_neg_prompt = f'({style_neg_prompt}:{style_neg_strength:.2f})' if style_neg_prompt is not None and style_neg_prompt.strip(' ,;') != '' else ''
        else:
            style_neg_prompt = f'{style_neg_prompt}' if style_neg_prompt is not None and style_neg_prompt.strip(' ,;') != '' else ''

        if (style_pos_prompt is not None and style_pos_prompt != '') or (style_neg_prompt is not None and style_neg_prompt != '') or model_concept != "Normal":
            copy_prompt_to_l = False

        if copy_prompt_to_l == True:
            sdxl_positive_l = positive_prompt
            sdxl_negative_l = negative_prompt

        if sdxl_l_strength != 1:
            sdxl_positive_l = f'({sdxl_positive_l}:{sdxl_l_strength:.2f})'.replace(":1.00", "") if sdxl_positive_l is not None and sdxl_positive_l.strip(' ,;') != '' else ''
            sdxl_negative_l = f'({sdxl_negative_l}:{sdxl_l_strength:.2f})'.replace(":1.00", "") if sdxl_negative_l is not None and sdxl_negative_l.strip(' ,;') != '' else ''
        else:
            sdxl_positive_l = f'{sdxl_positive_l}'.replace(":1.00", "") if sdxl_positive_l is not None and sdxl_positive_l.strip(' ,;') != '' else ''
            sdxl_negative_l = f'{sdxl_negative_l}'.replace(":1.00", "") if sdxl_negative_l is not None and sdxl_negative_l.strip(' ,;') != '' else ''

        if (style_pos_prompt.startswith('((') and style_pos_prompt.endswith('))')):
            style_pos_prompt = '(' + style_pos_prompt.strip('()') + ')'

        if (style_neg_prompt.startswith('((') and style_neg_prompt.endswith('))')):
            style_neg_prompt = '(' + style_neg_prompt.strip('()') + ')'

        if style_position == False:
            positive_text = f'{positive_prompt}, {opt_pos_prompt}, {style_pos_prompt}, {additional_positive}'.strip(' ,;').replace(", , ", ", ").replace(", , ", ", ").replace(":1.00", "")
            negative_text = f'{negative_prompt}, {opt_neg_prompt}, {style_neg_prompt}, {additional_negative}'.strip(' ,;').replace(", , ", ", ").replace(", , ", ", ").replace(":1.00", "")
        else:
            positive_text = f'{style_pos_prompt}, {opt_pos_prompt}, {positive_prompt}, {additional_positive}'.strip(' ,;').replace(", , ", ", ").replace(", , ", ", ").replace(":1.00", "")
            negative_text = f'{style_neg_prompt}, {opt_neg_prompt}, {negative_prompt}, {additional_negative}'.strip(' ,;').replace(", , ", ", ").replace(", , ", ", ").replace(":1.00", "")

        if model_keywords is not None:
            mkw_list = list(filter(None, model_keywords))
            if len(mkw_list) == 2:
                model_keyword = mkw_list[0]
                mplacement = mkw_list[1]
                if (mplacement == 'First'):
                    positive_text = model_keyword + ', ' + positive_text
                else:
                    positive_text = positive_text + ', ' + model_keyword

        if lora_keywords is not None:
            lkw_list = list(filter(None, lora_keywords))
            if len(lkw_list) == 2:
                lora_keyword = lkw_list[0]
                lplacement = lkw_list[1]
                if (lplacement == 'First'):
                    positive_text = lora_keyword + ', ' + positive_text
                else:
                    positive_text = positive_text + ', ' + lora_keyword

        if lycoris_keywords is not None:
            lykw_list = list(filter(None, lycoris_keywords))
            if len(lykw_list) == 2:
                lyco_keyword = lykw_list[0]
                lyplacement = lykw_list[1]
                if (lyplacement == 'First'):
                    positive_text = lyco_keyword + ', ' + positive_text
                else:
                    positive_text = positive_text + ', ' + lyco_keyword

        if embedding_pos is not None:
            embp_list = list(filter(None, embedding_pos))
            if len(embp_list) == 2:
                embp_keyword = embp_list[0]
                embp_placement = embp_list[1]
                if (embp_placement == 'First'):
                    positive_text = embp_keyword + ', ' + positive_text
                else:
                    positive_text = positive_text + ', ' + embp_keyword

        if embedding_neg is not None:
            embn_list = list(filter(None, embedding_neg))
            if len(embn_list) == 2:
                embn_keyword = embn_list[0]
                embn_placement = embn_list[1]
                if (embn_placement == 'First'):
                    negative_text = embn_keyword + ', ' + negative_text
                else:
                    negative_text = negative_text + ', ' + embn_keyword

        if (model_version == 'BaseModel_1024'):
            adv_encode = False

        if (use_long_clip == True and model_concept != 'Cascade'):
            LONGCLIPL_PATH = os.path.join(comfy_dir, 'models', 'clip')
            if os.path.exists(LONGCLIPL_PATH) == False:
                Path(LONGCLIPL_PATH).mkdir(parents=True, exist_ok=True)
            clipFiles = folder_paths.get_filename_list("clip")

            if 'longclip-L.pt' not in clipFiles:
                FileUrl = 'https://huggingface.co/BeichenZhang/LongCLIP-L/resolve/main/longclip-L.pt?download=true'
                FullFilePath = os.path.join(LONGCLIPL_PATH, 'longclip-L.pt')
                ModelDownload = utility.downloader(FileUrl, FullFilePath)
                if (ModelDownload == True):
                    clipFiles = folder_paths.get_filename_list("clip")

            if 'longclip-L.pt' in clipFiles:
                if (is_sdxl == 0):
                        class EmptyClass:
                            pass
                        clip_target = EmptyClass()
                        clip_path = folder_paths.get_full_path("clip", 'longclip-L.pt')
                        clip_target.params = {"version": clip_path}
                        clip_target.clip = clipping.SDLongClipModel
                        clip_target.tokenizer = clipping.SDLongTokenizer
                        embedding_directory = folder_paths.get_folder_paths("embeddings")
                        # clip = comfy.sd.CLIP(clip_target, embedding_directory=embedding_directory)
                        clip = clipping.LONGCLIP(clip_target, embedding_directory=embedding_directory)
                        adv_encode = False
                else:
                    clip_clone = clip.clone()
                    clip_path = folder_paths.get_full_path("clip", 'longclip-L.pt')
                    load_device = model_management.text_encoder_device()
                    device = model_management.text_encoder_offload_device()
                    dtype = model_management.text_encoder_dtype(load_device)
                    clip_l = clipping.SDLongClipModel(version=clip_path, layer="hidden", layer_idx=-2, device=device, dtype=dtype, layer_norm_hidden_state=False)
                    sdxl_long_clip_model = clipping.SDXLLongClipModel()
                    sdxl_long_clip_model.clip_l = clip_l
                    sdxl_long_clip_model.clip_g = clip_clone.cond_stage_model.clip_g
                    clip_clone.cond_stage_model = sdxl_long_clip_model
                    embedding_directory = folder_paths.get_folder_paths("embeddings")
                    long_tokenizer = clipping.SDXLLongTokenizer()
                    tokenizer_clip_l = clipping.SDLongTokenizer(embedding_directory=embedding_directory)
                    long_tokenizer.clip_l = tokenizer_clip_l
                    long_tokenizer.clip_g = clip_clone.tokenizer.clip_g
                    clip_clone.tokenizer = long_tokenizer
                    clip = clip_clone

        if (last_layer < 0):
            clip = nodes.CLIPSetLastLayer.set_last_layer(self, clip, last_layer)[0]

        if (adv_encode == True):
            if (is_sdxl == 0):

                if model_concept == 'Cascade':
                    positive_text = utility.clear_cascade(positive_text)
                    negative_text = utility.clear_cascade(negative_text)

                embeddings_final_pos, pooled_pos = advanced_encode(clip, positive_text, token_normalization, weight_interpretation, w_max = 1.0, apply_to_pooled = True)
                embeddings_final_neg, pooled_neg = advanced_encode(clip, negative_text, token_normalization, weight_interpretation, w_max = 1.0, apply_to_pooled = True)

                return ([[embeddings_final_pos, {"pooled_output": pooled_pos}]], [[embeddings_final_neg, {"pooled_output": pooled_neg}]], positive_text, negative_text, "", "")
            else:
                # embeddings_final_pos, pooled_pos = advanced_encode_XL(clip, sdxl_positive_l, positive_text, token_normalization, weight_interpretation, w_max = 1.0, clip_balance = sdxl_balance_l, apply_to_pooled = True)
                # embeddings_final_neg, pooled_neg = advanced_encode_XL(clip, sdxl_negative_l, negative_text, token_normalization, weight_interpretation, w_max = 1.0, clip_balance = sdxl_balance_l, apply_to_pooled = True)
                # return ([[embeddings_final_pos, {"pooled_output": pooled_pos}]],[[embeddings_final_neg, {"pooled_output": pooled_neg}]], positive_text, negative_text, sdxl_positive_l, sdxl_negative_l)
                if model_concept == 'Cascade':
                    positive_text = utility.clear_cascade(positive_text)
                    negative_text = utility.clear_cascade(negative_text)

                tokens_p = clip.tokenize(positive_text)
                if 'l' in clip.tokenize(sdxl_positive_l):
                    tokens_p["l"] = clip.tokenize(sdxl_positive_l)["l"]
                    if len(tokens_p["l"]) != len(tokens_p["g"]):
                        empty = clip.tokenize("")
                        while len(tokens_p["l"]) < len(tokens_p["g"]):
                            tokens_p["l"] += empty["l"]
                        while len(tokens_p["l"]) > len(tokens_p["g"]):
                            tokens_p["g"] += empty["g"]

                tokens_n = clip.tokenize(negative_text)
                if 'l' in clip.tokenize(sdxl_negative_l):
                    tokens_n["l"] = clip.tokenize(sdxl_negative_l)["l"]

                    if len(tokens_n["l"]) != len(tokens_n["g"]):
                        empty = clip.tokenize("")
                        while len(tokens_n["l"]) < len(tokens_n["g"]):
                            tokens_n["l"] += empty["l"]
                        while len(tokens_n["l"]) > len(tokens_n["g"]):
                            tokens_n["g"] += empty["g"]

                cond_p, pooled_p = clip.encode_from_tokens(tokens_p, return_pooled = True)
                cond_n, pooled_n = clip.encode_from_tokens(tokens_n, return_pooled = True)

                return ([[cond_p, {"pooled_output": pooled_p, "width": width, "height": height, "crop_w": 0, "crop_h": 0, "target_width": width, "target_height": height}]], [[cond_n, {"pooled_output": pooled_n, "width": width, "height": height, "crop_w": 0, "crop_h": 0, "target_width": width, "target_height": height}]], positive_text, negative_text, sdxl_positive_l, sdxl_negative_l)

        else:
            if model_concept == 'Cascade':
                positive_text = utility.clear_cascade(positive_text)
                negative_text = utility.clear_cascade(negative_text)

            tokens = clip.tokenize(positive_text)
            cond_pos, pooled_pos = clip.encode_from_tokens(tokens, return_pooled = True)

            tokens = clip.tokenize(negative_text)
            cond_neg, pooled_neg = clip.encode_from_tokens(tokens, return_pooled = True)

            return ([[cond_pos, {"pooled_output": pooled_pos}]], [[cond_neg, {"pooled_output": pooled_neg}]], positive_text, negative_text, "", "")

class PrimereResolution:
    RETURN_TYPES = ("INT", "INT", "INT", "TUPLE",)
    RETURN_NAMES = ("WIDTH", "HEIGHT", "SQUARE_SHAPE", "MODEL_SHAPES")
    FUNCTION = "calculate_imagesize"
    CATEGORY = TREE_DASHBOARD

    @staticmethod
    def get_ratios(toml_path: str):
        with open(toml_path, "rb") as f:
            image_ratios = tomli.load(f)
        return image_ratios

    @ classmethod
    def INPUT_TYPES(cls):
        DEF_TOML_DIR = os.path.join(PRIMERE_ROOT, 'Toml')
        cls.sd_ratios = cls.get_ratios(os.path.join(DEF_TOML_DIR, "resolution_ratios.toml"))

        namelist = {}
        for sd_ratio_key in cls.sd_ratios:
            rationName = cls.sd_ratios[sd_ratio_key]['name']
            namelist[rationName] = sd_ratio_key

        cls.ratioNames = namelist

        return {
            "required": {
                "ratio": (list(namelist.keys()),),
                "basemodel_res": (utility.VALID_SHAPES, {"default": utility.VALID_SHAPES[1]}),
                "sdxlmodel_res": (utility.VALID_SHAPES, {"default": utility.VALID_SHAPES[2]}),
                "turbo_res": (utility.VALID_SHAPES, {"default": utility.VALID_SHAPES[0]}),
                "rnd_orientation": ("BOOLEAN", {"default": False}),
                "orientation": (["Horizontal", "Vertical"], {"default": "Horizontal"}),
                "round_to_standard": ("BOOLEAN", {"default": False}),

                "calculate_by_custom": ("BOOLEAN", {"default": False}),
                "custom_side_a": ("FLOAT", {"default": 1.6, "min": 1.0, "max": 100.0, "step": 0.05}),
                "custom_side_b": ("FLOAT", {"default": 2.8, "min": 1.0, "max": 100.0, "step": 0.05}),
            },
            "optional": {
                "seed": ("INT", {"default": 0, "min": -1, "max": 0xffffffffffffffff, "forceInput": True}),
                "model_version": ("STRING", {"default": 'BaseModel_1024', "forceInput": True}),
                "model_concept": ("STRING", {"default": "Normal", "forceInput": True}),
            }
        }

    def calculate_imagesize(self, ratio: str, basemodel_res: int, sdxlmodel_res: int, turbo_res: int, rnd_orientation: bool, orientation: str, round_to_standard: bool, calculate_by_custom: bool, custom_side_a: float, custom_side_b: float, seed: int = 0, model_version: str = "BaseModel_1024", model_concept = "Normal"):
        if seed < 1:
            seed = random.randint(0, 9)

        if rnd_orientation == True:
            if (seed % 2) == 0:
                orientation = "Horizontal"
            else:
                orientation = "Vertical"

        if model_version != 'SDXL_2048':
            square_shape = basemodel_res
        else:
            square_shape = sdxlmodel_res

        if model_concept == "Turbo":
            square_shape = turbo_res

        dimensions = utility.get_dimensions_by_shape(self, ratio, square_shape, orientation, round_to_standard, calculate_by_custom, custom_side_a, custom_side_b, 'STANDARD')
        dimension_x = dimensions[0]
        dimension_y = dimensions[1]

        MODEL_SHAPES = {'SD': basemodel_res, 'SDXL': sdxlmodel_res, 'TURBO': turbo_res}

        return (dimension_x, dimension_y, square_shape, MODEL_SHAPES)

class PrimereResolutionMultiplier:
    RETURN_TYPES = ("INT", "INT", "FLOAT", "IMAGE")
    RETURN_NAMES = ("WIDTH", "HEIGHT", "UPSCALE_RATIO", "IMAGE")
    FUNCTION = "multiply_imagesize"
    CATEGORY = TREE_DEPRECATED
    upscale_methods = ["nearest-exact", "bilinear", "area", "bicubic", "lanczos"]

    @ classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "use_multiplier": ("BOOLEAN", {"default": True}),
                "width": ('INT', {"forceInput": True, "default": 512}),
                "height": ('INT', {"forceInput": True, "default": 512}),
                "multiply_sd": ("FLOAT", {"default": 2.0, "min": 0.1, "max": 8.0, "step": 0.02}),
                "multiply_sdxl": ("FLOAT", {"default": 2.0, "min": 0.1, "max": 8.0, "step": 0.02}),
                "multiply_turbo": ("FLOAT", {"default": 2.0, "min": 0.1, "max": 8.0, "step": 0.02}),
            },
            "optional": {
                "model_version": ("STRING", {"default": 'BaseModel_1024', "forceInput": True}),
                "model_concept": ("STRING", {"default": "Normal", "forceInput": True}),
                "triggered_prescale": ("BOOLEAN", {"default": False}),
                "image": ("IMAGE", {"forceInput": True}),
                "area_trigger_mpx": ("FLOAT", {"default": 0.60, "min": 0.01, "max": round(pow(utility.MAX_RESOLUTION, 2) / 1000000, 2), "step": 0.01}),
                "area_target_mpx": ("FLOAT", {"default": 1.05, "min": 0.25, "max": round(pow(utility.MAX_RESOLUTION, 2) / 1000000, 2), "step": 0.01}),
                "upscale_model": (['None'] + folder_paths.get_filename_list("upscale_models"), {"default": 'None'}),
                "upscale_method": (cls.upscale_methods, {"default": 'bicubic'}),
            }
        }

    def multiply_imagesize(self, width: int, height: int, use_multiplier: bool, multiply_sd: float, multiply_sdxl: float, multiply_turbo: float, model_version: str = "BaseModel_1024", model_concept: str = "Normal", triggered_prescale = False, image = None, area_trigger_mpx = 0.60, area_target_mpx = 1.05, upscale_model = 'None', upscale_method = 'bicubic'):
        if use_multiplier == False:
            return (width, height, 1, image)

        is_sdxl = 0
        match model_version:
            case 'SDXL_2048':
                is_sdxl = 1

        if image is not None:
            width = image.shape[2]
            height = image.shape[1]

        if (is_sdxl == 1):
            dimension_x = round(width * multiply_sdxl)
            dimension_y = round(height * multiply_sdxl)
            ratio = round(multiply_sdxl, 2)
        else:
            dimension_x = round(width * multiply_sd)
            dimension_y = round(height * multiply_sd)
            ratio = round(multiply_sd, 2)

        if model_concept == "Turbo":
            dimension_x = round(width * multiply_turbo)
            dimension_y = round(height * multiply_turbo)
            ratio = round(multiply_turbo, 2)

        if triggered_prescale == True and use_multiplier == True:
            upscale_to_mpx = (dimension_x * dimension_y) / (1024 * 1024)
            area_trigger = area_trigger_mpx * (1000 * 1000)
            area_target = area_target_mpx * (1024 * 1024)
            area = width * height
            if area_trigger >= area:
                sourceMPXTrigger = area
                differenceTrigger = area_target / sourceMPXTrigger
                squareDiffTrigger = math.sqrt(differenceTrigger)
                if image is not None:
                    if upscale_model == 'None':
                        prescaledImage = nodes.ImageScaleBy.upscale(self, image, upscale_method, squareDiffTrigger)[0]
                    else:
                        loaded_upscale_model = nodes_upscale_model.UpscaleModelLoader.load_model(self, upscale_model)[0]
                        prescaledImage = nodes_upscale_model.ImageUpscaleWithModel.upscale(self, loaded_upscale_model, image)[0]

                    image = prescaledImage
                    width = prescaledImage.shape[2]
                    height = prescaledImage.shape[1]
                    newArea = width * height

                    if newArea > area_target:
                        differenceTrigger = area_target / newArea
                        squareDiffTrigger = math.sqrt(differenceTrigger)
                        prescaledImage = nodes.ImageScaleBy.upscale(self, image, upscale_method, squareDiffTrigger)[0]
                        image = prescaledImage
                        width = prescaledImage.shape[2]
                        height = prescaledImage.shape[1]

                    sourceMPX = (width * height) / (1024 * 1024)
                    difference = upscale_to_mpx / sourceMPX
                    squareDiff = math.sqrt(difference)
                    dimension_x = round(width * squareDiff)
                    dimension_y = round(height * squareDiff)
                    ratio = round(squareDiff, 2)

        return (dimension_x, dimension_y, ratio, image)


class PrimereResolutionMultiplierMPX:
    RETURN_TYPES = ("INT", "INT", "FLOAT", "IMAGE")
    RETURN_NAMES = ("WIDTH", "HEIGHT", "UPSCALE_RATIO", "IMAGE")
    FUNCTION = "multiply_imagesize_mpx"
    CATEGORY = TREE_DASHBOARD
    upscale_methods = ["nearest-exact", "bilinear", "area", "bicubic", "lanczos"]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "use_multiplier": ("BOOLEAN", {"default": True}),
                "width": ('INT', {"forceInput": True, "default": 512}),
                "height": ('INT', {"forceInput": True, "default": 512}),
                "upscale_to_mpx": ("FLOAT", {"default": 12.00, "min": 0.01, "max": 48.00, "step": 0.01}),
            },
            "optional": {
                "triggered_prescale": ("BOOLEAN", {"default": False}),
                "image": ("IMAGE", {"forceInput": True}),
                "area_trigger_mpx": ("FLOAT", {"default": 0.60, "min": 0.01, "max": round(pow(utility.MAX_RESOLUTION, 2) / 1000000, 2), "step": 0.01}),
                "area_target_mpx": ("FLOAT", {"default": 1.05, "min": 0.25, "max": round(pow(utility.MAX_RESOLUTION, 2) / 1000000, 2), "step": 0.01}),
                "upscale_model": (['None'] + folder_paths.get_filename_list("upscale_models"), {"default": 'None'}),
                "upscale_method": (cls.upscale_methods, {"default": 'bicubic'}),
            }
        }

    def multiply_imagesize_mpx(self, width: int, height: int, use_multiplier: bool, upscale_to_mpx: int, triggered_prescale = False, image = None, area_trigger_mpx = 0.60, area_target_mpx = 1.05, upscale_model = 'None', upscale_method = 'bicubic'):
        if use_multiplier == False or upscale_to_mpx < 0.01:
            return (width, height, 1, image)

        if image is not None:
            width = image.shape[2]
            height = image.shape[1]

        if triggered_prescale == True and use_multiplier == True:
            area_trigger = area_trigger_mpx * (1000 * 1000)
            area_target = area_target_mpx * (1024 * 1024)
            area = width * height
            if area_trigger >= area:
                sourceMPXTrigger = area
                differenceTrigger = area_target / sourceMPXTrigger
                squareDiffTrigger = math.sqrt(differenceTrigger)
                if image is not None:
                    if upscale_model == 'None':
                        prescaledImage = nodes.ImageScaleBy.upscale(self, image, upscale_method, squareDiffTrigger)[0]
                    else:
                        loaded_upscale_model = nodes_upscale_model.UpscaleModelLoader.load_model(self, upscale_model)[0]
                        prescaledImage = nodes_upscale_model.ImageUpscaleWithModel.upscale(self, loaded_upscale_model, image)[0]

                    image = prescaledImage
                    width = prescaledImage.shape[2]
                    height = prescaledImage.shape[1]
                    newArea = width * height

                    if newArea > area_target:
                        differenceTrigger = area_target / newArea
                        squareDiffTrigger = math.sqrt(differenceTrigger)
                        prescaledImage = nodes.ImageScaleBy.upscale(self, image, upscale_method, squareDiffTrigger)[0]
                        image = prescaledImage
                        width = prescaledImage.shape[2]
                        height = prescaledImage.shape[1]

        sourceMPX = (width * height) / (1024 * 1024)
        difference = upscale_to_mpx / sourceMPX
        squareDiff = math.sqrt(difference)
        dimension_x = round(width * squareDiff)
        dimension_y = round(height * squareDiff)
        ratio = round(squareDiff, 2)

        return (dimension_x, dimension_y, ratio, image)

class PrimereResolutionCoordinatorMPX:
    RETURN_TYPES = ("INT", "INT", "INT", "INT", "IMAGE", "INT", "INT", "IMAGE", "INT", "INT")
    RETURN_NAMES = ("REF_WIDTH", "REF_HEIGHT", "SLAVE_WIDTH", "SLAVE_HEIGHT", "RESIZED_REFERENCE", "REF_WIDTH_RES", "REF_HEIGHT_RES", "RESIZED_SLAVE", "SLAVE_WIDTH_RES", "SLAVE_HEIGHT_RES")
    FUNCTION = "imagesize_coordinator"
    CATEGORY = TREE_DASHBOARD
    upscale_methods = ["nearest-exact", "bilinear", "area", "bicubic", "lanczos"]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "use_resizer": ("BOOLEAN", {"default": True}),
                "reference_image": ("IMAGE", {"forceInput": True}),
                "slave_image": ("IMAGE", {"forceInput": True}),
                "resize_to_mpx": ("FLOAT", {"default": 1.00, "min": 0.01, "max": 48.00, "step": 0.01}),
                "keep_slave_ratio": ("BOOLEAN", {"default": False}),
                "upscale_model": (['None'] + folder_paths.get_filename_list("upscale_models"), {"default": 'None'}),
                "upscale_method": (cls.upscale_methods, {"default": 'lanczos'}),
            }
        }

    def imagesize_coordinator(self, use_resizer, reference_image, slave_image, resize_to_mpx, keep_slave_ratio, upscale_model, upscale_method):
        ref_width = 0
        ref_height = 0
        slave_width = 0
        slave_height = 0

        if reference_image is not None and slave_image is not None:
            ref_width = reference_image.shape[2]
            ref_height = reference_image.shape[1]
            slave_width = slave_image.shape[2]
            slave_height = slave_image.shape[1]

        if use_resizer == True:
            referenceMPX = (ref_width * ref_height) / (1024 * 1024)
            referenceDifference = resize_to_mpx / referenceMPX
            ref_squareDiff = math.sqrt(referenceDifference)
            ref_width_resized = round(ref_width * ref_squareDiff)
            ref_height_resized = round(ref_height * ref_squareDiff)
            slaveMPX = (slave_width * slave_height) / (1024 * 1024)
            slaveDifference = resize_to_mpx / slaveMPX
            slave_squareDiff = math.sqrt(slaveDifference)

            if keep_slave_ratio == True:
                slave_width_resized = round(slave_width * slave_squareDiff)
                slave_height_resized = round(slave_height * slave_squareDiff)
            else:
                slave_width_resized = ref_width_resized
                slave_height_resized = ref_height_resized

            if upscale_model == 'None':
                reference_image = nodes.ImageScaleBy.upscale(self, reference_image, upscale_method, ref_squareDiff)[0]
                if keep_slave_ratio == True:
                    slave_image = nodes.ImageScaleBy.upscale(self, slave_image, upscale_method, slave_squareDiff)[0]
                else:
                    slave_image = nodes.ImageScale.upscale(self, slave_image, upscale_method, slave_width_resized, slave_height_resized, "disabled")[0]
            else:
                loaded_upscale_model = nodes_upscale_model.UpscaleModelLoader.load_model(self, upscale_model)[0]

                reference_image_model = nodes_upscale_model.ImageUpscaleWithModel.upscale(self, loaded_upscale_model, reference_image)[0]
                reference_image = nodes.ImageScale.upscale(self, reference_image_model, upscale_method, ref_width_resized, ref_height_resized, "disabled")[0]

                if keep_slave_ratio == True:
                    slave_image_model = nodes_upscale_model.ImageUpscaleWithModel.upscale(self, loaded_upscale_model, slave_image)[0]
                    slave_image = nodes.ImageScaleBy.upscale(self, slave_image_model, upscale_method, slave_squareDiff)[0]

                slave_image = nodes.ImageScale.upscale(self, slave_image, upscale_method, slave_width_resized, slave_height_resized, "disabled")[0]

        else:
            ref_width_resized = ref_width
            ref_height_resized = ref_height
            slave_width_resized = slave_width
            slave_height_resized = slave_height

        return (ref_width, ref_height, slave_width, slave_height, reference_image, ref_width_resized, ref_height_resized, slave_image, slave_width_resized, slave_height_resized)

class PrimereStepsCfg:
  RETURN_TYPES = ("INT", "FLOAT")
  RETURN_NAMES = ("STEPS", "CFG")
  FUNCTION = "steps_cfg"
  CATEGORY = TREE_DEPRECATED

  @classmethod
  def INPUT_TYPES(cls):
    return {
      "required": {
        "steps": ("INT", {"default": 12, "min": 1, "max": 1000, "step": 1}),
        "cfg": ("FLOAT", {"default": 7, "min": 0.1, "max": 100, "step": 0.01}),
      },
    }

  def steps_cfg(self, steps = 12, cfg = 7):
    return (steps, round(cfg, 2),)

class PrimereClearPrompt:
  RETURN_TYPES = ("STRING", "STRING")
  RETURN_NAMES = ("PROMPT+", "PROMPT-")
  FUNCTION = "clean_prompt"
  CATEGORY = TREE_DASHBOARD

  @classmethod
  def INPUT_TYPES(cls):
      return {
          "required": {
              "model_version": ("STRING", {"default": 'BaseModel_1024', "forceInput": True}),
              "positive_prompt": ("STRING", {"forceInput": True}),
              "negative_prompt": ("STRING", {"forceInput": True}),
              "remove_only_if_sdxl": ("BOOLEAN", {"default": False}),
              "remove_comfy_embedding": ("BOOLEAN", {"default": False}),
              "remove_a1111_embedding": ("BOOLEAN", {"default": False}),
              "remove_lora": ("BOOLEAN", {"default": False}),
              "remove_lycoris": ("BOOLEAN", {"default": False}),
              "remove_hypernetwork": ("BOOLEAN", {"default": False}),
          },
          "optional": {
              "model_concept": ("STRING", {"default": "Normal", "forceInput": True}),
          }
      }

  def clean_prompt(self, positive_prompt, negative_prompt, remove_comfy_embedding, remove_a1111_embedding, remove_lora, remove_lycoris, remove_hypernetwork, remove_only_if_sdxl, model_version = 'BaseModel_1024', model_concept = "Normal"):
      NETWORK_START = []

      is_sdxl = 0
      match model_version:
          case 'SDXL_2048':
              is_sdxl = 1

      if remove_only_if_sdxl == True and is_sdxl == 0:
          return (positive_prompt, negative_prompt,)

      if remove_comfy_embedding == True:
          NETWORK_START.append('embedding:')

      if remove_lora == True:
          NETWORK_START.append('<lora:')

      if remove_lycoris == True:
          NETWORK_START.append('<lyco:')

      if remove_hypernetwork == True:
          NETWORK_START.append('<hypernet:')

      if remove_a1111_embedding == True:
          positive_prompt = positive_prompt.replace('embedding:', '')
          negative_prompt = negative_prompt.replace('embedding:', '')
          EMBEDDINGS = folder_paths.get_filename_list("embeddings")
          for embeddings_path in EMBEDDINGS:
              path = Path(embeddings_path)
              embedding_name = path.stem
              positive_prompt = re.sub("(\(" + embedding_name + ":\d+\.\d+\))|(\(" + embedding_name + ":\d+\))|(" + embedding_name + ":\d+\.\d+)|(" + embedding_name + ":\d+)|(" + embedding_name + ":)|(\(" + embedding_name + "\))|(" + embedding_name + ")", "", positive_prompt)
              negative_prompt = re.sub("(\(" + embedding_name + ":\d+\.\d+\))|(\(" + embedding_name + ":\d+\))|(" + embedding_name + ":\d+\.\d+)|(" + embedding_name + ":\d+)|(" + embedding_name + ":)|(\(" + embedding_name + "\))|(" + embedding_name + ")", "", negative_prompt)
              positive_prompt = re.sub(r'(, )\1+', r', ', positive_prompt).strip(', ').replace(' ,', ',')
              negative_prompt = re.sub(r'(, )\1+', r', ', negative_prompt).strip(', ').replace(' ,', ',')

      if len(NETWORK_START) > 0:
         NETWORK_END = ['\n', '>', ' ', ',', '}', ')', '|'] + NETWORK_START
         positive_prompt = utility.clear_prompt(NETWORK_START, NETWORK_END, positive_prompt)
         negative_prompt = utility.clear_prompt(NETWORK_START, NETWORK_END, negative_prompt)

      if model_concept == 'Cascade':
          positive_prompt = utility.clear_cascade(positive_prompt)
          negative_prompt = utility.clear_cascade(negative_prompt)

      return (positive_prompt, negative_prompt,)

class PrimereNetworkTagLoader:
  RETURN_TYPES = ("MODEL", "CLIP", "LORA_STACK", "LYCORIS_STACK", "HYPERNETWORK_STACK", "MODEL_KEYWORD", "MODEL_KEYWORD")
  RETURN_NAMES = ("MODEL", "CLIP", "LORA_STACK", "LYCORIS_STACK", "HYPERNETWORK_STACK", "LORA_KEYWORD", "LYCORIS_KEYWORD")
  FUNCTION = "load_networks"
  CATEGORY = TREE_DASHBOARD
  @classmethod
  def INPUT_TYPES(s):
      return {
          "required": {
              "model": ("MODEL",),
              "clip": ("CLIP",),
              "positive_prompt": ("STRING", {"forceInput": True}),
              "process_lora": ("BOOLEAN", {"default": True}),
              "process_lycoris": ("BOOLEAN", {"default": True}),
              "process_hypernetwork": ("BOOLEAN", {"default": True}),
              "hypernetwork_safe_load": ("BOOLEAN", {"default": True}),
              "copy_weight_to_clip": ("BOOLEAN", {"default": False}),
              "lora_clip_custom_weight": ("FLOAT", {"default": 1.0, "min": -10.0, "max": 10.0, "step": 0.01}),
              "lycoris_clip_custom_weight": ("FLOAT", {"default": 1.0, "min": -10.0, "max": 10.0, "step": 0.01}),

              "use_lora_keyword": ("BOOLEAN", {"default": False}),
              "lora_keyword_placement": (["First", "Last"], {"default": "Last"}),
              "lora_keyword_selection": (["Select in order", "Random select"], {"default": "Select in order"}),
              "lora_keywords_num": ("INT", {"default": 1, "min": 1, "max": 50, "step": 1}),
              "lora_keyword_weight": ("FLOAT", {"default": 1.0, "min": 0, "max": 10.0, "step": 0.1}),

              "use_lycoris_keyword": ("BOOLEAN", {"default": False}),
              "lycoris_keyword_placement": (["First", "Last"], {"default": "Last"}),
              "lycoris_keyword_selection": (["Select in order", "Random select"], {"default": "Select in order"}),
              "lycoris_keywords_num": ("INT", {"default": 1, "min": 1, "max": 50, "step": 1}),
              "lycoris_keyword_weight": ("FLOAT", {"default": 1.0, "min": 0, "max": 10.0, "step": 0.1}),
          }
      }

  def load_networks(self, model, clip, positive_prompt, process_lora, process_lycoris, process_hypernetwork, copy_weight_to_clip, lora_clip_custom_weight, lycoris_clip_custom_weight, use_lora_keyword, use_lycoris_keyword, lora_keyword_placement, lycoris_keyword_placement, lora_keyword_selection, lycoris_keyword_selection, lora_keywords_num, lycoris_keywords_num, lora_keyword_weight, lycoris_keyword_weight, hypernetwork_safe_load = True):
      NETWORK_START = []

      cloned_model = model
      cloned_clip = clip
      list_of_keyword_items = []
      lora_keywords_num_set = lora_keywords_num
      lycoris_keywords_num_set = lycoris_keywords_num
      model_lora_keyword = [None, None]
      model_lyco_keyword = [None, None]
      lora_stack = []
      lycoris_stack = []
      hnet_stack = []

      HypernetworkList = folder_paths.get_filename_list("hypernetworks")
      LoraList = folder_paths.get_filename_list("loras")

      LYCO_DIR = os.path.join(comfy_dir, 'models', 'lycoris')
      folder_paths.add_model_folder_path("lycoris", LYCO_DIR)
      LyCORIS = folder_paths.get_filename_list("lycoris")
      LycorisList = folder_paths.filter_files_extensions(LyCORIS, ['.ckpt', '.safetensors'])

      if process_lora == True:
        NETWORK_START.append('<lora:')

      if process_lycoris == True:
        NETWORK_START.append('<lyco:')

      if process_hypernetwork == True:
        NETWORK_START.append('<hypernet:')

      if len(NETWORK_START) == 0:
          return (model, clip, lora_stack, lycoris_stack, hnet_stack, model_lora_keyword, model_lyco_keyword)
      else:
          NETWORK_END = ['>'] + NETWORK_START
          NETWORK_TUPLE = utility.get_networks_prompt(NETWORK_START, NETWORK_END, positive_prompt)
          if (len(NETWORK_TUPLE) == 0):
              return (model, clip, lora_stack, lycoris_stack, hnet_stack, model_lora_keyword, model_lyco_keyword)
          else:
              for NETWORK_DATA in NETWORK_TUPLE:
                  NetworkName = NETWORK_DATA[0]
                  try:
                    NetworkStrenght = float(NETWORK_DATA[1])
                  except ValueError:
                    NetworkStrenght = 1
                  NetworkType = NETWORK_DATA[2]

                  if (process_lora == True and NetworkType == 'LORA'):
                      lora_name = utility.get_closest_element(NetworkName, LoraList)
                      if lora_name is not None:
                          lora_path = folder_paths.get_full_path("loras", lora_name)
                          lora = comfy.utils.load_torch_file(lora_path, safe_load=True)
                          if (copy_weight_to_clip == True):
                              lora_clip_custom_weight = NetworkStrenght
                          lora_stack.append([lora_name, NetworkStrenght, lora_clip_custom_weight])
                          cloned_model, cloned_clip = comfy.sd.load_lora_for_models(cloned_model, cloned_clip, lora, NetworkStrenght, lora_clip_custom_weight)

                          if use_lora_keyword == True:
                              ModelKvHash = utility.get_model_hash(lora_path)
                              if ModelKvHash is not None:
                                  KEYWORD_PATH = os.path.join(PRIMERE_ROOT, 'front_end', 'keywords', 'lora-keyword.txt')
                                  keywords = utility.get_model_keywords(KEYWORD_PATH, ModelKvHash, lora_name)
                                  if keywords is not None and keywords != "" and isinstance(keywords, str) == True:
                                      if keywords.find('|') > 1:
                                          keyword_list = [word.strip() for word in keywords.split('|')]
                                          keyword_list = list(filter(None, keyword_list))
                                          if (len(keyword_list) > 0):
                                              lora_keywords_num = lora_keywords_num_set
                                              keyword_qty = len(keyword_list)
                                              if (lora_keywords_num > keyword_qty):
                                                  lora_keywords_num = keyword_qty
                                              if lora_keyword_selection == 'Select in order':
                                                  list_of_keyword_items.extend(keyword_list[:lora_keywords_num])
                                              else:
                                                  list_of_keyword_items.extend(random.sample(keyword_list, lora_keywords_num))
                                      else:
                                          list_of_keyword_items.append(keywords)

                      if len(list_of_keyword_items) > 0:
                          if lora_keyword_selection != 'Select in order':
                              random.shuffle(list_of_keyword_items)

                          list_of_keyword_items = list(set(list_of_keyword_items))
                          keywords = ", ".join(list_of_keyword_items)

                          if (lora_keyword_weight != 1):
                              keywords = '(' + keywords + ':' + str(round(lora_keyword_weight, 1)) + ')'

                          model_lora_keyword = [keywords, lora_keyword_placement]

                  if (process_lycoris == True and NetworkType == 'LYCORIS'):
                      lycoris_name = utility.get_closest_element(NetworkName, LycorisList)
                      if lycoris_name is not None:
                          lycoris_path = folder_paths.get_full_path("lycoris", lycoris_name)
                          lycoris = comfy.utils.load_torch_file(lycoris_path, safe_load=True)
                          if (copy_weight_to_clip == True):
                              lycoris_clip_custom_weight = NetworkStrenght
                          lycoris_stack.append([lycoris_name, NetworkStrenght, lycoris_clip_custom_weight])
                          cloned_model, cloned_clip = comfy.sd.load_lora_for_models(cloned_model, cloned_clip, lycoris, NetworkStrenght, lycoris_clip_custom_weight)

                          if use_lycoris_keyword == True:
                              ModelKvHash = utility.get_model_hash(lycoris_path)
                              if ModelKvHash is not None:
                                  KEYWORD_PATH = os.path.join(PRIMERE_ROOT, 'front_end', 'keywords', 'lora-keyword.txt')
                                  keywords = utility.get_model_keywords(KEYWORD_PATH, ModelKvHash, lycoris_name)
                                  if keywords is not None and keywords != "" and isinstance(keywords, str) == True:
                                      if keywords.find('|') > 1:
                                          keyword_list = [word.strip() for word in keywords.split('|')]
                                          keyword_list = list(filter(None, keyword_list))
                                          if (len(keyword_list) > 0):
                                              lycoris_keywords_num = lycoris_keywords_num_set
                                              keyword_qty = len(keyword_list)
                                              if (lycoris_keywords_num > keyword_qty):
                                                  lycoris_keywords_num = keyword_qty
                                              if lycoris_keyword_selection == 'Select in order':
                                                  list_of_keyword_items.extend(keyword_list[:lycoris_keywords_num])
                                              else:
                                                  list_of_keyword_items.extend(random.sample(keyword_list, lycoris_keywords_num))
                                      else:
                                          list_of_keyword_items.append(keywords)

                      if len(list_of_keyword_items) > 0:
                          if lycoris_keyword_selection != 'Select in order':
                              random.shuffle(list_of_keyword_items)

                          list_of_keyword_items = list(set(list_of_keyword_items))
                          keywords = ", ".join(list_of_keyword_items)

                          if (lycoris_keyword_weight != 1):
                              keywords = '(' + keywords + ':' + str(round(lycoris_keyword_weight, 1)) + ')'

                          model_lyco_keyword = [keywords, lycoris_keyword_placement]

                  if (process_hypernetwork == True and NetworkType == 'HYPERNET'):
                      hyper_name = utility.get_closest_element(NetworkName, HypernetworkList)
                      if hyper_name is not None:
                          hypernetwork_path = folder_paths.get_full_path("hypernetworks", hyper_name)
                          model_hypernetwork = cloned_model.clone()
                          try:
                            patch = hypernetwork.load_hypernetwork_patch(hypernetwork_path, NetworkStrenght, hypernetwork_safe_load)
                          except Exception:
                              patch = None
                          if patch is not None:
                              model_hypernetwork.set_model_attn1_patch(patch)
                              model_hypernetwork.set_model_attn2_patch(patch)
                              hnet_stack.append([hyper_name, NetworkStrenght])
                              cloned_model = model_hypernetwork

      return (cloned_model, cloned_clip, lora_stack, lycoris_stack, hnet_stack, model_lora_keyword, model_lyco_keyword)

class PrimereModelKeyword:
    RETURN_TYPES = ("MODEL_KEYWORD",)
    RETURN_NAMES = ("MODEL_KEYWORD",)
    FUNCTION = "load_ckpt_keyword"
    CATEGORY = TREE_DASHBOARD

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model_name": ('CHECKPOINT_NAME', {"forceInput": True, "default": ""}),
                "use_model_keyword": ("BOOLEAN", {"default": False}),
                "model_keyword_placement": (["First", "Last"], {"default": "Last"}),
                # "model_keyword_selection": (["Select in order", "Random select"], {"default": "Select in order"}),
                "model_keywords_num": ("INT", {"default": 1, "min": 1, "max": 50, "step": 1}),
                "model_keyword_weight": ("FLOAT", {"default": 1.0, "min": 0, "max": 10.0, "step": 0.1}),
            },
            "hidden": {
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    def load_ckpt_keyword(self, model_name, use_model_keyword, model_keyword_placement, model_keywords_num, model_keyword_weight, **kwargs):
        model_keyword = [None, None]

        WORKFLOWDATA = kwargs['extra_pnginfo']['workflow']['nodes']
        selectedKeyword = utility.getDataFromWorkflow(WORKFLOWDATA, 'PrimereModelKeyword', 4)

        if use_model_keyword == True and selectedKeyword != 'None' and selectedKeyword != None:
            if selectedKeyword != 'Select in order' and selectedKeyword != 'Random select':
                if selectedKeyword.rfind('/') != -1:
                    selectedKeyword = selectedKeyword.rsplit('/', 1)[1].strip()
                if (model_keyword_weight != 1):
                    selectedKeyword = '(' + selectedKeyword + ':' + str(round(model_keyword_weight, 1)) + ')'

                model_keyword = [selectedKeyword, model_keyword_placement]
            else:
                ckpt_path = folder_paths.get_full_path("checkpoints", model_name)
                ModelKvHash = utility.get_model_hash(ckpt_path)
                if ModelKvHash is not None:
                    KEYWORD_PATH = os.path.join(PRIMERE_ROOT, 'front_end', 'keywords', 'model-keyword.txt')
                    keywords = utility.get_model_keywords(KEYWORD_PATH, ModelKvHash, model_name)

                    if keywords is not None and isinstance(keywords, str) == True:
                        if keywords.find('|') > 1:
                            keyword_list = keywords.split("|")
                            if (len(keyword_list) > 0):
                                keyword_qty = len(keyword_list)
                                if (model_keywords_num > keyword_qty):
                                    model_keywords_num = keyword_qty
                                if selectedKeyword == 'Select in order':
                                    list_of_keyword_items = keyword_list[:model_keywords_num]
                                else:
                                    list_of_keyword_items = random.sample(keyword_list, model_keywords_num)

                                clean_keywords = []
                                for keyword_item in list_of_keyword_items:
                                    if keyword_item.rfind('/') != -1:
                                        keyword_item = keyword_item.rsplit('/', 1)[1].strip()
                                    clean_keywords += [keyword_item]

                                keywords = ", ".join(clean_keywords)

                        if (model_keyword_weight != 1):
                            keywords = '(' + keywords + ':' + str(round(model_keyword_weight, 1)) + ')'

                        model_keyword = [keywords, model_keyword_placement]

        return (model_keyword,)

class PrimereConceptDataTuple:
    RETURN_TYPES = ("TUPLE",)
    RETURN_NAMES = ("CONCEPT_DATA",)
    FUNCTION = "load_concept_collector"
    CATEGORY = TREE_DASHBOARD

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "lightning_selector": ("STRING", {"default": "SAFETENSOR", "forceInput": True}),
                "lightning_model_step": ("INT", {"default": 8, "forceInput": True}),

                "cascade_stage_a": ("STRING", {"forceInput": True}),
                "cascade_stage_b": ("STRING", {"forceInput": True}),
                "cascade_stage_c": ("STRING", {"forceInput": True}),
                "cascade_clip": ("STRING", {"forceInput": True}),

                "hypersd_selector": ("STRING", {"default": "LORA", "forceInput": True}),
                "hypersd_model_step": ("INT", {"default": 8, "forceInput": True}),
            },
        }

    def load_concept_collector(self, **kwargs):
        return (kwargs,)

class PrimereUpscaleModel:
    RETURN_TYPES = ("UPSCALE_MODEL", folder_paths.get_filename_list("upscale_models"),)
    RETURN_NAMES = ("UPSCALE_MODEL", 'MODEL_NAME',)
    FUNCTION = "load_upscaler"
    CATEGORY = TREE_DASHBOARD
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model_name": (folder_paths.get_filename_list("upscale_models"), ),
            }
        }

    def load_upscaler(self, model_name):
        out = nodes_upscale_model.UpscaleModelLoader.load_model(self, model_name)[0]
        return (out, model_name,)