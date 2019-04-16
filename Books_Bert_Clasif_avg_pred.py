from pathlib import Path
import pandas as pd
from examples.run_lm_finetuning import *
from examples.run_classifier import *

#Reading dataset
path = Path('Books_bert')
df_test = pd.read_csv(path/'test_books.csv',header=0)#Test set with the number of paragraphs depending on the length of the document.
paragr_to_books = df_test['Book']#I keep the books in a separate series
df_test.drop(columns='Book', inplace=True)
df_test.columns = [0, 2]

#df_train = pd.read_csv('ag_news_csv/train.csv',header=None)
print(df_train.head())
# df_train.drop(columns=1, inplace=True)
# df_test.drop(columns=1, inplace=True)
# frames=[df_train, df_test]
# df_for_lm = pd.concat(frames)
# df_for_lm = df_for_lm[2].str.cat(sep = '\n')

# Hyperparameter and config values
output_dir = path
bert_model = 'bert-base-uncased'
do_lower_case = True
gradient_accumulation_steps = 1
max_seq_length = 256
on_memory = True
train_batch_size = 16
num_train_epochs = 2
learning_rate = 3e-5
local_rank = -1
fp16 = True
loss_scale = 0
warmup_proportion = 0.1
do_train = False
n_gpu = torch.cuda.device_count()
device='cuda'
do_eval = True
eval_batch_size = train_batch_size
cache_dir = ''
Books_pretrained_weights = path / 'books_clasif.bin'
num_labels = 5
#Labels corresponding to  ['Computers', 'Business', 'Health', 'Romance', 'Horror']
label_list = [0, 1, 2, 3, 4]

def get_train_examples(train_df): #Modif for Books dataset from Dataframe
    examples=[]
    for i,line in train_df.iterrows():
        examples.append(
            InputExample(guid=i, text_a=line[2], text_b=None, label=line[0]))
    return examples

tokenizer = BertTokenizer.from_pretrained(bert_model, do_lower_case=do_lower_case)

train_examples = None
num_train_optimization_steps = None
if do_train:
    train_examples = get_train_examples(df_train)
    num_train_optimization_steps = int(
        len(train_examples) / train_batch_size / gradient_accumulation_steps) * num_train_epochs
    if local_rank != -1:
        num_train_optimization_steps = num_train_optimization_steps // torch.distributed.get_world_size()

# Prepare model
cache_dir = cache_dir if cache_dir else os.path.join(str(PYTORCH_PRETRAINED_BERT_CACHE),
                                                               'distributed_{}'.format(local_rank))

model_state_dict = torch.load(Books_pretrained_weights)
model = BertForSequenceClassification.from_pretrained(bert_model,
                                                      cache_dir=cache_dir, state_dict = model_state_dict,
                                                      num_labels=num_labels)#DANI Añado state_dict para incluir el modelo entrenado
if fp16:
    model.half()
model.to(device)
if local_rank != -1:
    try:
        from apex.parallel import DistributedDataParallel as DDP
    except ImportError:
        raise ImportError(
            "Please install apex from https://www.github.com/nvidia/apex to use distributed and fp16 training.")

    model = DDP(model)
elif n_gpu > 1:
    model = torch.nn.DataParallel(model)

# Prepare optimizer
param_optimizer = list(model.named_parameters())
no_decay = ['bias', 'LayerNorm.bias', 'LayerNorm.weight']
optimizer_grouped_parameters = [
    {'params': [p for n, p in param_optimizer if not any(nd in n for nd in no_decay)], 'weight_decay': 0.01},
    {'params': [p for n, p in param_optimizer if any(nd in n for nd in no_decay)], 'weight_decay': 0.0}
]
if fp16:
    try:
        from apex.optimizers import FP16_Optimizer
        from apex.optimizers import FusedAdam
    except ImportError:
        raise ImportError(
            "Please install apex from https://www.github.com/nvidia/apex to use distributed and fp16 training.")

    optimizer = FusedAdam(optimizer_grouped_parameters,
                          lr=learning_rate,
                          bias_correction=False,
                          max_grad_norm=1.0)
    if loss_scale == 0:
        optimizer = FP16_Optimizer(optimizer, dynamic_loss_scale=True)
    else:
        optimizer = FP16_Optimizer(optimizer, static_loss_scale=loss_scale)

else:
    optimizer = BertAdam(optimizer_grouped_parameters,
                         lr=learning_rate,
                         warmup=warmup_proportion,
                         t_total=num_train_optimization_steps)

global_step = 0
nb_tr_steps = 0
tr_loss = 0
if do_train:
    train_features = convert_examples_to_features(train_examples, label_list, max_seq_length, tokenizer)
    logger.info("***** Running training *****")
    logger.info("  Num examples = %d", len(train_examples))
    logger.info("  Batch size = %d", train_batch_size)
    logger.info("  Num steps = %d", num_train_optimization_steps)
    all_input_ids = torch.tensor([f.input_ids for f in train_features], dtype=torch.long)
    all_input_mask = torch.tensor([f.input_mask for f in train_features], dtype=torch.long)
    all_segment_ids = torch.tensor([f.segment_ids for f in train_features], dtype=torch.long)
    all_label_ids = torch.tensor([f.label_id for f in train_features], dtype=torch.long)
    train_data = TensorDataset(all_input_ids, all_input_mask, all_segment_ids, all_label_ids)
    if local_rank == -1:
        train_sampler = RandomSampler(train_data)
    else:
        train_sampler = DistributedSampler(train_data)
    train_dataloader = DataLoader(train_data, sampler=train_sampler, batch_size=train_batch_size)

    model.train()
    for _ in trange(int(num_train_epochs), desc="Epoch"):
        tr_loss = 0
        nb_tr_examples, nb_tr_steps = 0, 0
        for step, batch in enumerate(tqdm(train_dataloader, desc="Iteration")):
            batch = tuple(t.to(device) for t in batch)
            input_ids, input_mask, segment_ids, label_ids = batch
            loss = model(input_ids, segment_ids, input_mask, label_ids)
            if n_gpu > 1:
                loss = loss.mean()  # mean() to average on multi-gpu.
            if gradient_accumulation_steps > 1:
                loss = loss / gradient_accumulation_steps

            if fp16:
                optimizer.backward(loss)
            else:
                loss.backward()

            tr_loss += loss.item()
            nb_tr_examples += input_ids.size(0)
            nb_tr_steps += 1
            if (step + 1) % gradient_accumulation_steps == 0:
                if fp16:
                    # modify learning rate with special warm up BERT uses
                    # if args.fp16 is False, BertAdam is used that handles this automatically
                    lr_this_step = learning_rate * warmup_linear(global_step / num_train_optimization_steps,
                                                                      warmup_proportion)
                    for param_group in optimizer.param_groups:
                        param_group['lr'] = lr_this_step
                optimizer.step()
                optimizer.zero_grad()
                global_step += 1

if do_train:
    # Save a trained model and the associated configuration
    model_to_save = model.module if hasattr(model, 'module') else model  # Only save the model it-self
    output_model_file = os.path.join(output_dir, WEIGHTS_NAME)
    torch.save(model_to_save.state_dict(), output_model_file)
    output_config_file = os.path.join(output_dir, CONFIG_NAME)
    with open(output_config_file, 'w') as f:
        f.write(model_to_save.config.to_json_string())

    # Load a trained model and config that you have fine-tuned
    config = BertConfig(output_config_file)
    model = BertForSequenceClassification(config, num_labels=num_labels)
    model.load_state_dict(torch.load(output_model_file))
else:
    model = BertForSequenceClassification.from_pretrained(bert_model, state_dict = model_state_dict,num_labels=num_labels)#DANI añado state_dict
model.to(device)

if do_eval and (local_rank == -1 or torch.distributed.get_rank() == 0):
    eval_examples = get_train_examples(df_test)
    eval_features = convert_examples_to_features(
        eval_examples, label_list, max_seq_length, tokenizer)
    logger.info("***** Running evaluation *****")
    logger.info("  Num examples = %d", len(eval_examples))
    logger.info("  Batch size = %d", eval_batch_size)
    all_input_ids = torch.tensor([f.input_ids for f in eval_features], dtype=torch.long)
    all_input_mask = torch.tensor([f.input_mask for f in eval_features], dtype=torch.long)
    all_segment_ids = torch.tensor([f.segment_ids for f in eval_features], dtype=torch.long)
    all_label_ids = torch.tensor([f.label_id for f in eval_features], dtype=torch.long)
    eval_data = TensorDataset(all_input_ids, all_input_mask, all_segment_ids, all_label_ids)
    # Run prediction for full data
    eval_sampler = SequentialSampler(eval_data)
    eval_dataloader = DataLoader(eval_data, sampler=eval_sampler, batch_size=eval_batch_size)

    model.eval()
    eval_loss, eval_accuracy = 0, 0
    nb_eval_steps, nb_eval_examples = 0, 0

    logits_concat = np.empty([0,5])#DANI I create this array to concat all logits
    label_ids_concat = np.empty([0])#DANI
    for input_ids, input_mask, segment_ids, label_ids in tqdm(eval_dataloader, desc="Evaluating"):
        input_ids = input_ids.to(device)
        input_mask = input_mask.to(device)
        segment_ids = segment_ids.to(device)
        label_ids = label_ids.to(device)

        with torch.no_grad():
            tmp_eval_loss = model(input_ids, segment_ids, input_mask, label_ids)
            logits = model(input_ids, segment_ids, input_mask)

        logits = logits.detach().cpu().numpy()
        label_ids = label_ids.to('cpu').numpy()
    #-------------------------------------DANI-------------------------------------
        logits_concat = np.concatenate((logits_concat, logits), axis=0)#DANI
        label_ids_concat = np.concatenate((label_ids_concat, label_ids), axis=0)#DANI

    parag_counts = paragr_to_books.value_counts().sort_index(ascending=False)
    logits_index = 0
    label_ids_reduc = np.empty([0])
    logits_concat_reduc = np.empty([0,5])
    for count in parag_counts:

        logits_concat_reduc = np.concatenate((logits_concat_reduc, logits_concat[logits_index:logits_index + count, :].mean(axis=0).reshape([1, 5])), axis=0)
        label_ids_reduc = np.append(label_ids_reduc, label_ids_concat[logits_index])
        logits_index = logits_index + count


    tmp_eval_accuracy = accuracy(logits_concat_reduc, label_ids_reduc)#I take it out of the loop to use the new logits_concat

    #eval_loss += tmp_eval_loss.mean().item()
    #eval_accuracy += tmp_eval_accuracy
    eval_accuracy = tmp_eval_accuracy/len(label_ids_reduc)
    # nb_eval_examples += input_ids.size(0)
    # nb_eval_steps += 1

    #eval_loss = eval_loss / nb_eval_steps
    #eval_accuracy = eval_accuracy / nb_eval_examples
    #loss = tr_loss / nb_tr_steps if do_train else None
    result = {#'eval_loss': eval_loss,
              'eval_accuracy': eval_accuracy#,
              #'global_step': global_step,
              #'loss': loss
                }

    output_eval_file = os.path.join(output_dir, "eval_results.txt")
    with open(output_eval_file, "w") as writer:
        logger.info("***** Eval results *****")
        for key in sorted(result.keys()):
            logger.info("  %s = %s", key, str(result[key]))
            writer.write("%s = %s\n" % (key, str(result[key])))