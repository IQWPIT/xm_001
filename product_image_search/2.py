# -*- coding: utf-8 -*-

import os
import json
from collections import defaultdict
from pymongo import UpdateOne
from tqdm import tqdm

os.environ["NET"] = "TUNNEL"
os.environ["NET3"] = "NXQ"

from dm.connector.mongo.manager3 import get_collection
site = "ml_mx"
sku = get_collection(f"main_{site}",site,"sku")
