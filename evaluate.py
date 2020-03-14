'''
This file uses the offical evaluation script for SQuAD version 2.0.

It takes as input a directory created by qa_probes_iterative.py,
which corresponds to predictions made after a certain epoch

It then writes those predictions to json, and evaluates those predictions

'''




"""Official evaluation script for SQuAD version 2.0.

In addition to basic functionality, we also compute additional statistics and
plot precision-recall curves if an additional na_prob.json file is provided.
This file is expected to map question ID's to the model's predicted probability
that a question is unanswerable.
"""
import argparse
import collections
import json
import numpy as np
import os
import re
import string
import sys
import glob
import csv, json
import pandas as pd

def make_qid_to_has_ans(dataset):
  qid_to_has_ans = {}
  for article in dataset:
    for p in article['paragraphs']:
      for qa in p['qas']:
        qid_to_has_ans[qa['id']] = bool(qa['answers'])
  return qid_to_has_ans

def normalize_answer(s):
  """Lower text and remove punctuation, articles and extra whitespace."""
  def remove_articles(text):
    regex = re.compile(r'\b(a|an|the)\b', re.UNICODE)
    return re.sub(regex, ' ', text)
  def white_space_fix(text):
    return ' '.join(text.split())
  def remove_punc(text):
    exclude = set(string.punctuation)
    return ''.join(ch for ch in text if ch not in exclude)
  def lower(text):
    return text.lower()
  return white_space_fix(remove_articles(remove_punc(lower(s))))

def get_tokens(s):
  if not s: return []
  return normalize_answer(s).split()

def compute_exact(a_gold, a_pred):
  return int(normalize_answer(a_gold) == normalize_answer(a_pred))

def compute_f1(a_gold, a_pred):
  gold_toks = get_tokens(a_gold)
  pred_toks = get_tokens(a_pred)
  common = collections.Counter(gold_toks) & collections.Counter(pred_toks)
  num_same = sum(common.values())
  if len(gold_toks) == 0 or len(pred_toks) == 0:
    # If either is no-answer, then F1 is 1 if they agree, 0 otherwise
    return int(gold_toks == pred_toks)
  if num_same == 0:
    return 0
  precision = 1.0 * num_same / len(pred_toks)
  recall = 1.0 * num_same / len(gold_toks)
  f1 = (2 * precision * recall) / (precision + recall)
  return f1

def get_raw_scores(dataset, preds):
  exact_scores = {}
  f1_scores = {}
  for article in dataset:
    for p in article['paragraphs']:
      for qa in p['qas']:
        qid = qa['id']
        gold_answers = [a['text'] for a in qa['answers']
                        if normalize_answer(a['text'])]
        if not gold_answers:
          # For unanswerable questions, only correct answer is empty string
          gold_answers = ['']
        if qid not in preds:
          print('Missing prediction for %s' % qid)
          continue
        a_pred = preds[qid]
        # Take max over all gold answers
        exact_scores[qid] = max(compute_exact(a, a_pred) for a in gold_answers)
        f1_scores[qid] = max(compute_f1(a, a_pred) for a in gold_answers)
  return exact_scores, f1_scores

def apply_no_ans_threshold(scores, na_probs, qid_to_has_ans, na_prob_thresh):
  new_scores = {}
  for qid, s in scores.items():
    pred_na = na_probs[qid] > na_prob_thresh
    if pred_na:
      new_scores[qid] = float(not qid_to_has_ans[qid])
    else:
      new_scores[qid] = s
  return new_scores

def make_eval_dict(exact_scores, f1_scores, qid_list=None):
  if not qid_list:
    total = len(exact_scores)
    return collections.OrderedDict([
        ('exact', 100.0 * sum(exact_scores.values()) / total),
        ('f1', 100.0 * sum(f1_scores.values()) / total),
        ('total', total),
    ])
  else:
    total = len(qid_list)
    return collections.OrderedDict([
        ('exact', 100.0 * sum(exact_scores[k] for k in qid_list) / total),
        ('f1', 100.0 * sum(f1_scores[k] for k in qid_list) / total),
        ('total', total),
    ])

def merge_eval(main_eval, new_eval, prefix):
  for k in new_eval:
    main_eval['%s_%s' % (prefix, k)] = new_eval[k]

def main(data_file, pred_file, mode):
  with open(data_file) as f:
    dataset_json = json.load(f)
    dataset = dataset_json['data']
  
  with open(pred_file) as f:
    preds = json.load(f)
  na_probs = {k: 0.0 for k in preds}
  
  qid_to_has_ans = make_qid_to_has_ans(dataset)  # maps qid to True/False
  has_ans_qids = [k for k, v in qid_to_has_ans.items() if v]
  no_ans_qids = [k for k, v in qid_to_has_ans.items() if not v]
  
  exact_raw, f1_raw = get_raw_scores(dataset, preds)
  
  exact_thresh = apply_no_ans_threshold(exact_raw, na_probs, qid_to_has_ans,1.0)
  f1_thresh = apply_no_ans_threshold(f1_raw, na_probs, qid_to_has_ans, 1.0)
  
  out_eval = make_eval_dict(exact_thresh, f1_thresh)

  if mode == 'Has_Ans' or mode == 'All':
    if has_ans_qids:
      has_ans_eval = make_eval_dict(exact_thresh, f1_thresh, qid_list=has_ans_qids)
      merge_eval(out_eval, has_ans_eval, 'HasAns')
  
  if mode == 'No_Ans' or mode == 'All':
    if no_ans_qids:
      no_ans_eval = make_eval_dict(exact_thresh, f1_thresh, qid_list=no_ans_qids)
      merge_eval(out_eval, no_ans_eval, 'NoAns')

  print(out_eval['exact'], out_eval['f1'])
  return out_eval['exact'], out_eval['f1']


def convert_preds_to_json(pred_dir):
    for csv_file in glob.glob(pred_dir + "*.csv"):

        if csv_file == pred_dir + "*" + "results.csv":
            continue

        prefix = csv_file[:-4]

        data = {}
        with open(csv_file) as f:
            r = csv.DictReader(f)
            for row in r:
                id = row['Id']
                pred = row['Predicted']
                data[id] = pred

        x = json.dumps(data)
        f = open(prefix + ".json", "w")
        f.write(x)
        f.close()

def save_metrics(pred_dir, dev_file, mode):

    layers = np.array([1,2,3,4,5,6,7,8,9,10,11,12])
    exact = np.zeros(12)
    f1 = np.zeros(12)

    for json_file in glob.glob(pred_dir + "*.json"):

        layer = int(json_file[len(pred_dir) + len("pred_layer_"):-5])
        exact_score, f1_score = main(dev_file, json_file, mode)
        exact[layer - 1] = exact_score
        f1[layer - 1] = f1_score
        print(layer, exact_score, f1_score)

    results = pd.DataFrame({'layer':layers, 'exact':exact, 'f1':f1})
    
    save_dir = os.path.abspath(pred_dir+"/../")
    csv_name = mode + "results.csv"

    results.to_csv(save_dir+csv_name, index = False)

if __name__ == '__main__':

  pred_dir = sys.argv[1]
  dev_file = "squad-master/data/dev-v2.0.json"

  if pred_dir[-1] != "/":
      pred_dir = pred_dir + "/"

  modes = ['Has_Ans', 'No_Ans', 'All']
  for mode in modes:
    print("For mode={}".format(mode))
    convert_preds_to_json(pred_dir)
    save_metrics(pred_dir, dev_file, mode)
