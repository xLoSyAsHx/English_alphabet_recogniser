import os, time, itertools
import torch
import numpy as np
import matplotlib.pyplot as plt

from matplotlib.backends.backend_agg import FigureCanvasAgg
from sklearn.metrics import roc_curve, auc
from torchvision.utils import make_grid
from scipy import interp

from alphabet_recogniser.utils import Config


def log(tag, text, glogal_step=0):
    print(text)
    Config.get_instance().writer.add_text(tag, text, glogal_step)


def autolabel(rects, ax, fontsize):
    for rect in rects:
        height = rect.get_height()
        ax.annotate(f'{int(height)}',
                    xy=(rect.get_x() + rect.get_width() / 2, height),
                    xytext=(0, 3),  # 3 points vertical offset
                    fontsize=fontsize,
                    textcoords="offset points",
                    ha='center', va='bottom')


def save_model(net, acc, epoch):
    config = Config.get_instance()
    if config.args.m_save_path is None:
        return

    save_path = os.path.join(
                       config.args.m_save_path,
                       f"{config.log_pref}"
                       f"_acc[{acc}]"
                       f"_e[{epoch}]"
                       f"_c[{net.num_classes}]"
                       f"_tr_s[{config.train_size_per_class if config.train_size_per_class is not None else 'All'}]"
                       f"_t_s[{config.test_size_per_class if config.test_size_per_class is not None else 'All'}]"
                       f".model")

    if not os.path.exists(save_path):
        torch.save(net, save_path)


def upload_net_graph(net, test_loader):
    config = Config.get_instance()
    if config.args.t_images is None:
        with torch.no_grad():
            net.to('cpu')
            config.writer.add_graph(net)
            net.to(config.device)
            return

    with torch.no_grad():
        images = iter(test_loader).next()[0][:config.args.t_images]
        images = images.to('cpu')
        net.to('cpu')
        config.writer.add_image('MNIST19 preprocessed samples', make_grid(images))
        config.writer.add_graph(net, images)
        net.to(config.device)


def add_logs_to_tensorboard(metrics, epoch):
    config = Config.get_instance()
    start_time = time.perf_counter()

    classes = [config.classes[key]['chr'] for key in config.classes]

    def can_log(frequence):
        return (epoch % frequence == 0 and epoch != 0) or (epoch % frequence != 0 and config.epoch_num - 1 == epoch)

    if can_log(config.args.t_cm_freq):
        log_conf_matrix(metrics, classes, epoch)

    if can_log(config.args.t_precision_bar_freq):
        log_TPR_PPV_F1_bars(metrics, classes, epoch)

    if can_log(config.args.t_roc_auc_freq):
        log_ROC_AUC(metrics, classes, epoch)

    return time.perf_counter() - start_time


def add_fig_to_tensorboard(fig, tag, step, close=True):
    agg = fig.canvas.switch_backends(FigureCanvasAgg)
    agg.draw()

    img = np.fromstring(agg.tostring_rgb(), dtype=np.uint8, sep='')
    img = img.reshape(agg.get_width_height()[::-1] + (3,))

    # Normalize into 0-1 range for TensorBoard(X). Swap axes for newer versions where API expects colors in first dim
    img = img / 255.0
    img = np.swapaxes(img, 0, 2)
    img = np.swapaxes(img, 1, 2)

    Config.get_instance().writer.add_image(tag, img, step)
    if close:
        plt.close(fig)


# G - global variables
# M - metrics
def log_conf_matrix(M, classes, step, title='Confusion matrix', tensor_name ='MyFigure/image', normalize=False):
    cm = M.cm
    if normalize:
        cm = cm.astype('float')*10 / cm.sum(axis=1)[:, np.newaxis]
        cm = np.nan_to_num(cm, copy=True)
        cm = cm.astype('int')

    np.set_printoptions(precision=2)
    fig, ax = plt.subplots(figsize=(7, 7), dpi=200, facecolor='w', edgecolor='k')
    ax.imshow(M.cm, cmap='Oranges')

    tick_marks = np.arange(len(classes))
    fontsize = 23 - round(len(classes) / (1.5 if len(classes) > 13 else 0.8))

    ax.set_xlabel('Predicted', fontsize=fontsize)
    ax.set_xticks(tick_marks)
    c = ax.set_xticklabels(classes, fontsize=fontsize, ha='center')
    ax.xaxis.set_label_position('bottom')
    ax.xaxis.tick_bottom()

    ax.set_ylabel('True Label', fontsize=fontsize)
    ax.set_yticks(tick_marks)
    ax.set_yticklabels(classes, fontsize=fontsize, va ='center')
    ax.yaxis.set_label_position('left')
    ax.yaxis.tick_left()
    ax.set_title('Confusion matrix')

    for i, j in itertools.product(range(cm.shape[0]), range(cm.shape[1])):
        ax.text(j, i, format(cm[i, j], 'd') if cm[i,j]!=0 else '.', horizontalalignment="center", fontsize=fontsize, verticalalignment='center', color= "black")

    fig.set_tight_layout(True)
    if step is not None:
        add_fig_to_tensorboard(fig, 'confusion_matrix', step)


# G - global variables
# M - metrics
def log_TPR_PPV_F1_bars(M, classes, step):
    fontsize = 24 - round(len(classes) / (1.5 if len(classes) > 13 else 0.8))

    multiplier = 3
    total_width = 0.75 * multiplier
    el_width = total_width / 3
    x = np.arange(0, len(classes) * multiplier, multiplier)
    np.set_printoptions(precision=2)
    fig, ax = plt.subplots(figsize=(11, 7), dpi=200, facecolor='w', edgecolor='k')
    rects_TPR = ax.bar(x - total_width / 2 + el_width * 0.5, M.TPR * 100, width=el_width, align='center', label='Recall')
    rects_PPV = ax.bar(x - total_width / 2 + el_width * 1.5, M.PPV * 100, width=el_width, align='center', label='Precision')
    rects_F1  = ax.bar(x - total_width / 2 + el_width * 2.5, M.F1  * 100, width=el_width, align='center', label='F1 score', color='r')


    ax.set_ylim([0, 110])
    ax.set_xlabel('Classes', fontsize=fontsize + 5)
    ax.set_ylabel('Percents', fontsize=fontsize + 5)
    ax.set_xticks(x)
    ax.set_xticklabels(classes, fontsize=fontsize, ha='center')
    ax.set_title('Recall / Precision / F1')
    ax.grid()
    ax.legend(loc='best')

    autolabel(rects_TPR, ax, fontsize - 3)
    autolabel(rects_PPV, ax, fontsize - 3)
    autolabel(rects_F1,  ax, fontsize - 3)

    fig.set_tight_layout(True)
    if step is not None:
        add_fig_to_tensorboard(fig, 'recall/precision/F1', step)


# G - global variables
# M - metrics
def log_ROC_AUC(M, classes, step):
    fpr = dict()
    tpr = dict()
    interp_tprs = []
    roc_auc = dict()
    mean_fpr = np.linspace(0, 1, 100)
    for i in range(len(classes)):
        fpr[i], tpr[i], _ = roc_curve(
            M.pred_list[M.lbl_list == i] == M.lbl_list[M.lbl_list == i],
            M.prob_list[M.lbl_list == i])
        roc_auc[i] = auc(fpr[i], tpr[i])

        interp_tpr = interp(mean_fpr, fpr[i], tpr[i])
        interp_tpr[0] = 0.0
        interp_tprs.append(interp_tpr)

    np.set_printoptions(precision=2)
    fig, ax = plt.subplots(figsize=(9, 7), dpi=200, facecolor='w', edgecolor='k')

    for i in range(len(classes)):
        ax.plot(fpr[i], tpr[i], label=f"ROC '{classes[i]}' (AUC = {roc_auc[i]:0.2f})", linewidth=0.5, alpha=0.5)
    ax.plot([0, 1], [0, 1],     label='Chance', color='r', linestyle='--')

    mean_tpr = np.mean(interp_tprs, axis=0)
    mean_tpr[-1] = 1.0
    mean_auc = auc(mean_fpr, mean_tpr)
    std_auc = np.std([roc_auc[key] for key in roc_auc])
    ax.plot(mean_fpr, mean_tpr, color='b',
            label=rf'Mean ROC (AUC = {mean_auc:0.2f} $\pm$ {std_auc:0.2f})', lw=2, alpha=0.8)

    std_tpr = np.std(interp_tprs, axis=0)
    tprs_upper = np.minimum(mean_tpr + std_tpr, 1)
    tprs_lower = np.maximum(mean_tpr - std_tpr, 0)
    ax.fill_between(mean_fpr, tprs_lower, tprs_upper, color='grey', alpha=0.2,
                    label=r'$\pm$ 1 std. dev.')

    ax.set_xlim([0.0, 1.0])
    ax.set_ylim([0.0, 1.1])
    ax.set_xlabel('False Positive Rate')
    ax.set_ylabel('True Positive Rate')
    ax.set_title('ROC curves')
    ax.grid()
    # ax.legend(loc='lower right')
    ax.legend(loc='center left', bbox_to_anchor=(1, 0.5))

    fig.set_tight_layout(True)
    if step is not None:
        add_fig_to_tensorboard(fig, 'ROC-AUC', step)
